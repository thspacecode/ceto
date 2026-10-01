"""Credit domain service for Ceto carts (gift cards and store credits).

A ``Ceto Credit Wallet`` (the provider-backed balance) is applied to a cart by
booking a ``Ceto Cart Credit Reservation`` — the public credit line — and
writing the applied amount as a negative ``Actual`` row on the Quotation
``taxes`` table, keyed on the company's default receivable account. The
Quotation keeps saving through ERPNext's own controllers, so ERPNext remains
the totals authority; Ceto only books the deduction rows its reservations
dictate.

- Gift cards resolve by the SHA-256 hash of the submitted code, scoped to the
  cart's company; the plaintext code never reaches the database and only the
  wallet's masked hint is serialized back.
- Store credits resolve per authenticated customer, company and currency;
  reapplying replaces the cart's prior store-credit reservation(s).
- Every wallet read that leads to a reservation first locks the wallet row
  (``SELECT … FOR UPDATE``, the same row-lock discipline as the cart), so
  concurrent applications of one wallet serialize and availability is
  reservation-aware inside the lock.
- :meth:`CartCredits.reconcile` runs inside the cart lock after every
  totals-moving mutation: holds are re-capped to what the cart can absorb and
  the deduction rows are rebuilt from the surviving holds, so a tax-template
  reload heals on the same save and the booked deductions can never drive the
  totals negative.
- Availability always derives from the ledger totals (``credit_total -
  debit_total``) of the row under lock, never from the stored ``balance``
  snapshot; overlapping carts lock wallets in sorted-name order so they
  cannot deadlock each other.
- Claiming never transfers another customer's money: customer-owned
  store-credit holds of a different customer are released before the
  re-priced save (:meth:`CartCredits.release_foreign_store_credits`), and a
  cancelled or deleted Quotation releases its open holds
  (:func:`release_quotation_credit_holds`, hooked in ``ceto/hooks.py``) so
  no hold outlives the payable it was booked against.
- Completion consumes the money (:meth:`CartCredits.consume_cart_credits`):
  inside the cart lock the wallets behind the cart's open holds are locked
  in sorted-name order, each hold is debited into its wallet's ledger
  (``debit_total``) and flipped to ``Consumed``. The negative deduction
  rows already booked on the Quotation ride the ERPNext mapper onto the
  Sales Order, so the placed order's grand total stays net of the consumed
  credits. Reads for the placed order (:meth:`CartCredits.consumed_credits`)
  return the consumed holds of the completed cart's Quotation — the
  order-credit view the order serializer reports.
"""
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import flt, get_datetime, now_datetime

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems

if TYPE_CHECKING:
	from frappe.model.document import Document

GIFT_CARD_NOT_FOUND = "Gift card not found"
GIFT_CARD_EXPIRED = "Gift card has expired"
GIFT_CARD_CURRENCY = "Gift card is not available for the cart's currency"
GIFT_CARD_EXHAUSTED = "Gift card has no available balance"
GIFT_CARD_NO_PAYABLE = "Gift card cannot be applied to a cart without an amount payable"
GIFT_CARD_NOT_APPLIED = "Gift card is not applied to the cart"
STORE_CREDIT_WALLET_MISSING = "No store credit is available for this customer and currency"
STORE_CREDIT_EXPIRED = "Store credit has expired"
STORE_CREDITS_EXCEEDED = "Store credit amount exceeds the available balance"
STORE_CREDITS_EXHAUSTED = "Store credit has no available balance"
STORE_CREDITS_NO_PAYABLE = "Store credits cannot be applied to a cart without an amount payable"


def hash_code(code: str) -> str:
	"""Return the lowercase SHA-256 hex digest of ``code``; codes are never stored in plaintext."""
	return hashlib.sha256(code.strip().encode()).hexdigest()


def new_credit_line_id() -> str:
	"""Return a stable public credit-line id: ``cl_`` + 128 bits of crypto random."""
	return f"cl_{secrets.token_hex(16)}"


@dataclass(frozen=True)
class AppliedCredit:
	"""One open cart credit hold, as the serializer reports it."""

	credit_line_id: str
	wallet: str
	reference: str
	code_hint: str | None
	amount: float
	creation: datetime
	modified: datetime


class CartCredits:
	"""Gift-card and store-credit operations on the Quotation backing a cart."""

	@classmethod
	def apply_gift_card(cls, quotation: "Document", code: str) -> None:
		"""Resolve ``code`` and hold the card's available balance on the cart.

		Called inside the cart row lock; a failing resolution (unknown code,
		wrong currency, expired or exhausted card, no amount payable) raises
		before any mutation and the caller's transaction rolls back.
		Re-applying an already applied card is idempotent: the single open
		hold is re-derived by the reconciliation instead of a second hold
		being booked.
		"""
		wallet = cls._locked_wallet(
			{"company": quotation.company, "code_hash": hash_code(code), "wallet_type": "Gift Card"}
		)
		if wallet is None:
			raise InvalidDataError(GIFT_CARD_NOT_FOUND)
		cls._validate_expiry(wallet, GIFT_CARD_EXPIRED)
		if wallet.currency != quotation.currency:
			raise InvalidDataError(GIFT_CARD_CURRENCY)
		if cls._open_reservation(quotation.name, wallet.name) is not None:
			cls.reconcile(quotation)
			return
		available = cls._available_balance(wallet)
		if available <= 0:
			raise InvalidDataError(GIFT_CARD_EXHAUSTED)
		if cls._payable(quotation) <= 0:
			raise InvalidDataError(GIFT_CARD_NO_PAYABLE)
		cls._reserve(quotation, wallet, available)
		cls.reconcile(quotation)

	@classmethod
	def remove_gift_card(cls, quotation: "Document", code: str) -> None:
		"""Release the hold booked for ``code`` and restore the totals.

		Called inside the cart row lock. An unknown code and a code that is
		not applied to this cart are both request errors raised before any
		mutation.
		"""
		wallet = cls._locked_wallet(
			{"company": quotation.company, "code_hash": hash_code(code), "wallet_type": "Gift Card"}
		)
		if wallet is None:
			raise InvalidDataError(GIFT_CARD_NOT_FOUND)
		hold = cls._open_reservation(quotation.name, wallet.name)
		if hold is None:
			raise InvalidDataError(GIFT_CARD_NOT_APPLIED)
		cls.release(hold)
		cls.reconcile(quotation)

	@classmethod
	def apply_store_credits(cls, quotation: "Document", customer: str, amount: float | None) -> None:
		"""Hold store credit for ``customer`` on the cart.

		Called inside the cart row lock after the customer was resolved from
		the authenticated session. Without ``amount`` the whole available
		balance is reserved; an explicit amount must not exceed it. Either
		way the hold is re-capped to what the cart can absorb. Reapplying
		releases the cart's prior store-credit reservation(s) first, so the
		request replaces the previous application instead of stacking holds.
		"""
		wallet = cls._locked_wallet(
			{
				"company": quotation.company,
				"currency": quotation.currency,
				"customer": customer,
				"wallet_type": "Store Credit",
			}
		)
		if wallet is None:
			raise InvalidDataError(STORE_CREDIT_WALLET_MISSING)
		cls._validate_expiry(wallet, STORE_CREDIT_EXPIRED)
		for prior in cls._open_store_credit_reservations(quotation.name):
			cls.release(prior)
		available = cls._available_balance(wallet)
		requested = available if amount is None else flt(amount)
		if amount is not None and requested > available:
			raise InvalidDataError(STORE_CREDITS_EXCEEDED)
		if requested <= 0:
			raise InvalidDataError(STORE_CREDITS_EXHAUSTED)
		if cls._payable(quotation) <= 0:
			raise InvalidDataError(STORE_CREDITS_NO_PAYABLE)
		cls._reserve(quotation, wallet, requested)
		cls.reconcile(quotation)

	@classmethod
	def stage_for_mutation(cls, quotation: "Document") -> None:
		"""Unbook the deduction rows ahead of a shrinking cart mutation.

		The line-item, promotion, shipping and re-pricing mutations persist
		an intermediate save through ERPNext's own validation, which rejects
		a negative ``Grand Total (Company Currency)``; a deduction booked
		against a larger payable would drive the shrunken cart below zero
		before the reconciliation can re-cap the holds. Dropping the rows
		first keeps that intermediate save valid, and :meth:`reconcile` —
		always called right after inside the same locked section — rebooks
		the surviving holds' rows from scratch.
		"""
		for row in cls.deduction_rows(quotation):
			quotation.remove(row)

	@classmethod
	def release_foreign_store_credits(cls, quotation: "Document", customer: str) -> list[str]:
		"""Release the cart's store-credit holds owned by a different customer.

		A guest cart can carry holds from any customer who applied before the
		claim, and claiming must not transfer that money into the claiming
		customer's cart. Wallet rows are locked first — in sorted name order,
		the same deterministic order as :meth:`locked_wallets` — so the
		release serializes against a concurrent application of the same
		wallet. Returns the released hold names; the following reconciliation
		rebuilds the deduction rows from the surviving holds.
		"""
		holds = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation.name, "status": "Reserved"},
			fields=["name", "wallet"],
		)
		if not holds:
			return []
		holds_by_wallet: dict[str, list[str]] = {}
		for hold in holds:
			holds_by_wallet.setdefault(hold.wallet, []).append(hold.name)
		foreign: list[str] = []
		for wallet_name in sorted(holds_by_wallet):
			wallet = frappe.db.get_value(
				"Ceto Credit Wallet",
				wallet_name,
				["name", "wallet_type", "customer"],
				as_dict=True,
				for_update=True,
			)
			if (
				wallet is not None
				and wallet.wallet_type == "Store Credit"
				and wallet.customer
				and wallet.customer != customer
			):
				foreign.extend(holds_by_wallet[wallet_name])
		for hold in foreign:
			cls.release(hold)
		return foreign

	@classmethod
	def reconcile(cls, quotation: "Document") -> None:
		"""Re-cap the cart's open holds and rewrite the deduction rows.

		Called inside the cart row lock after every totals-moving mutation.
		Each hold is bounded by what its wallet can still back and by the
		cart's remaining deductible amount, so the booked deductions can
		never drive ``total`` negative. A gift card always earmarks its
		wallet's whole remaining balance, so its hold re-derives — down
		**and** back up — as the cart changes; a store credit keeps the
		requested amount and is only ever capped down. Holds that lose all
		value, or whose wallet no longer matches the cart's company or
		currency, are released.
		"""
		rows = cls.deduction_rows(quotation)
		reservations = cls._open_reservations(quotation)
		if not reservations and not rows:
			return
		deductible = cls._payable(quotation)
		for row in rows:
			quotation.remove(row)
		wallets = cls.locked_wallets(reservations)
		released = []
		for reservation in reservations:
			capped = cls._cap(quotation, reservation, wallets.get(reservation.wallet), deductible)
			deductible = flt(deductible - capped)
			if capped <= 0:
				released.append(reservation.name)
				continue
			if flt(reservation.amount) != capped:
				frappe.db.set_value("Ceto Cart Credit Reservation", reservation.name, "amount", capped)
			cls._append_deduction_row(quotation, wallets.get(reservation.wallet), reservation, capped)
		for hold in released:
			cls.release(hold)
		if quotation.items:
			# ERPNext recalculates every summary field from the rows — the
			# deduction included — so the totals stay ERPNext's own output.
			quotation.calculate_taxes_and_totals()
		CartLineItems.save(quotation)

	@classmethod
	def applied_credits(cls, quotation_name: str) -> list[AppliedCredit]:
		"""Return the cart's open holds in application order.

		Read-only view for serialization: only ``Reserved`` reservations
		count — released or consumed holds no longer reduce what the cart
		owes and drop out of ``gift_cards`` and ``credit_lines``.
		"""
		return cls._credits(quotation_name, "Reserved")

	@classmethod
	def consumed_credits(cls, quotation_name: str) -> list[AppliedCredit]:
		"""Return the holds completion consumed on the cart, oldest first.

		Order-credit read for the placed order's serialization: the holds
		are keyed on the completed cart's Quotation (the payable they were
		booked against), and only ``Consumed`` ones count — released holds
		never became money and stay out of the order's credit totals.
		"""
		return cls._credits(quotation_name, "Consumed")

	@classmethod
	def _credits(cls, quotation_name: str, status: str) -> list[AppliedCredit]:
		rows = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation_name, "status": status},
			fields=["credit_line_id", "wallet", "amount", "creation", "modified"],
			order_by="creation asc, name asc",
		)
		wallets: dict[str, dict] = {}
		credits = []
		for row in rows:
			wallet = wallets.get(row.wallet)
			if wallet is None:
				wallet = (
					frappe.db.get_value(
						"Ceto Credit Wallet", row.wallet, ["wallet_type", "code_hint"], as_dict=True
					)
					or {}
				)
				wallets[row.wallet] = wallet
			credits.append(
				AppliedCredit(
					credit_line_id=row.credit_line_id,
					wallet=row.wallet,
					reference="gift-card" if wallet.get("wallet_type") == "Gift Card" else "store-credit",
					code_hint=wallet.get("code_hint"),
					amount=flt(row.amount),
					creation=get_datetime(row.creation),
					modified=get_datetime(row.modified),
				)
			)
		return credits

	@classmethod
	def consume_cart_credits(cls, quotation: "Document") -> None:
		"""Debit the wallets behind the cart's open holds and consume the holds.

		Called inside the cart row lock during completion, after the Sales
		Order exists. Wallet rows are locked first in sorted-name order (the
		same deterministic order as :meth:`_locked_wallets`, so completion
		can never deadlock a concurrent application of the same wallet), then
		every open hold is debited into its wallet's ledger — ``debit_total``
		grows by the held amount and the stored ``balance`` snapshot is
		refreshed from the totals — and the hold is flipped to ``Consumed``:
		a consumed hold stops counting against the balance, like a released
		one. The negative deduction rows already booked on the Quotation ride
		the ERPNext mapper onto the Sales Order, so the placed order's grand
		total stays net of the consumed credits and the ledger reflects the
		same money. Everything happens in the caller's transaction: a failure
		rolls the whole completion back and no wallet is ever half-debited.
		"""
		holds = cls._open_reservations(quotation)
		if not holds:
			return
		wallets = cls._locked_wallets(holds)
		for hold in holds:
			wallet = wallets.get(hold.wallet)
			if wallet is None:
				# Unreachable through the cart flow (the reconciliation
				# releases holds whose wallet is gone); fail loudly rather
				# than book money without a wallet.
				frappe.throw(f"Wallet {hold.wallet} of credit line {hold.credit_line_id} is missing")
			amount = flt(hold.amount)
			debit_total = flt(wallet.debit_total) + amount
			frappe.db.set_value(
				"Ceto Credit Wallet",
				hold.wallet,
				{"debit_total": debit_total, "balance": flt(wallet.credit_total) - debit_total},
			)
			frappe.db.set_value("Ceto Cart Credit Reservation", hold.name, "status", "Consumed")

	@classmethod
	def deduction_rows(cls, quotation: "Document") -> list["Document"]:
		"""Return the negative ``Actual`` rows booking the cart's deductions.

		The rows Ceto writes are recognizable without a marker field: an
		``Actual`` charge on the company's default receivable account with a
		negative amount — ERPNext itself never books that shape on a cart
		Quotation (the Shipping Rule charge is positive on an income
		account, discounts are not tax rows).
		"""
		account = cls._deduction_account(quotation.company)
		if not account:
			return []
		return [
			row
			for row in quotation.get("taxes") or []
			if row.get("charge_type") == "Actual"
			and row.get("account_head") == account
			and flt(row.get("tax_amount")) < 0
		]

	@staticmethod
	def release(hold: str) -> None:
		"""Mark ``hold`` released: it stops counting against the balance."""
		frappe.db.set_value("Ceto Cart Credit Reservation", hold, "status", "Released")

	@classmethod
	def _payable(cls, quotation: "Document") -> float:
		"""Return the grand total before this cart's credit deductions.

		ERPNext recalculated the totals on the last save with the negative
		rows booked, so adding the booked deductions back yields the amount
		the holds may absorb.
		"""
		return flt(quotation.grand_total) + flt(
			sum(-flt(row.tax_amount) for row in cls.deduction_rows(quotation))
		)

	@staticmethod
	def _locked_wallet(filters: dict) -> "Document | None":
		"""Return the wallet row under a row lock, or ``None``.

		``SELECT … FOR UPDATE`` on the wallet serializes every reservation a
		concurrent request could book against the same balance; the
		reservation-aware availability below is computed under this lock.
		"""
		return frappe.db.get_value("Ceto Credit Wallet", filters, "*", as_dict=True, for_update=True)

	@classmethod
	def locked_wallets(cls, reservations: list[dict]) -> dict[str, "Document | None"]:
		"""Lock and map the wallets behind ``reservations`` (one lock each).

		Locks are taken in sorted wallet-name order, so two carts whose holds
		overlap on the same wallets can never deadlock each other by locking
		the same rows in opposite orders. ``name`` and the ledger totals are
		projected because :meth:`_cap` excludes the hold's own reservation by
		name and derives availability from the totals, never from the stored
		``balance`` snapshot.
		"""
		wallets: dict[str, "Document | None"] = {}
		for wallet_name in sorted({reservation.wallet for reservation in reservations}):
			wallets[wallet_name] = frappe.db.get_value(
				"Ceto Credit Wallet",
				wallet_name,
				["name", "company", "currency", "wallet_type", "code_hint", "credit_total", "debit_total"],
				as_dict=True,
				for_update=True,
			)
		return wallets

	@staticmethod
	def _validate_expiry(wallet: "Document", message: str) -> None:
		if wallet.expires_at and wallet.expires_at < now_datetime():
			raise InvalidDataError(message)

	@classmethod
	def _available_balance(cls, wallet: "Document") -> float:
		"""Return the wallet balance net of every open hold on any cart."""
		return cls._ledger_balance(wallet) - cls._reserved_excluding(wallet.name, None)

	@staticmethod
	def _ledger_balance(wallet: "Document | dict") -> float:
		"""Return the wallet's ledger balance: ``credit_total - debit_total``.

		The totals are the ledger's authority; the stored ``balance`` column
		is only a snapshot that a provider booking bypassing the DocType
		validate could leave stale.
		"""
		return flt(wallet.credit_total) - flt(wallet.debit_total)

	@classmethod
	def _reserved_excluding(cls, wallet: str, hold: str | None) -> float:
		"""Sum the wallet's open ``Reserved`` holds except ``hold``."""
		filters = {"wallet": wallet, "status": "Reserved"}
		if hold:
			filters["name"] = ("!=", hold)
		reserved = frappe.get_all("Ceto Cart Credit Reservation", filters=filters, pluck="amount")
		return flt(sum(flt(amount) for amount in reserved))

	@classmethod
	def _open_reservation(cls, quotation: str, wallet: str) -> str | None:
		"""Return the cart's open hold on ``wallet``, if any."""
		return frappe.db.get_value(
			"Ceto Cart Credit Reservation",
			{"quotation": quotation, "wallet": wallet, "status": "Reserved"},
			"name",
		)

	@classmethod
	def _open_store_credit_reservations(cls, quotation: str) -> list[str]:
		"""Return every open hold on ``quotation`` backed by a store-credit wallet."""
		holds = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation, "status": "Reserved"},
			fields=["name", "wallet"],
		)
		wallets = {
			row.name: row.wallet_type
			for row in frappe.get_all(
				"Ceto Credit Wallet",
				filters={"name": ("in", [hold.wallet for hold in holds])} if holds else {},
				fields=["name", "wallet_type"],
			)
		}
		return [hold.name for hold in holds if wallets.get(hold.wallet) == "Store Credit"]

	@classmethod
	def _cap(
		cls, quotation: "Document", reservation: dict, wallet: "Document | None", remaining: float
	) -> float:
		"""Return the amount ``reservation`` may still hold.

		Bounded by the wallet's reservation-aware availability, the hold's
		own target (the wallet balance for gift cards, the requested amount
		for store credits) and the cart's remaining deductible amount.
		"""
		if wallet is None or wallet.company != quotation.company or wallet.currency != quotation.currency:
			# A cart that moved to another company or currency (region
			# switch) cannot keep holds denominated for the old one.
			return 0.0
		available = cls._ledger_balance(wallet) - cls._reserved_excluding(wallet.name, reservation.name)
		target = available if wallet.wallet_type == "Gift Card" else min(flt(reservation.amount), available)
		return max(min(flt(target), remaining), 0.0)

	@classmethod
	def _reserve(cls, quotation: "Document", wallet: "Document", amount: float) -> "Document":
		"""Insert the credit-line hold; the DocType validate re-checks it."""
		return frappe.get_doc(
			{
				"doctype": "Ceto Cart Credit Reservation",
				"credit_line_id": new_credit_line_id(),
				"wallet": wallet.name,
				"quotation": quotation.name,
				"currency": quotation.currency,
				"amount": amount,
				"status": "Reserved",
			}
		).insert(ignore_permissions=True)

	@classmethod
	def _append_deduction_row(
		cls, quotation: "Document", wallet: "Document | None", reservation: dict, amount: float
	) -> None:
		"""Book ``amount`` as a negative ``Actual`` row on the receivable account.

		The receivable credit is what reduces the customer's outstanding
		total; ``calculate_taxes_and_totals`` (called by the reconciliation)
		folds it into the ERPNext-computed grand total.
		"""
		account = cls._deduction_account(quotation.company)
		if not account:
			frappe.throw(
				_("Company {0} has no default receivable account to book cart credits against").format(
					quotation.company
				)
			)
		if wallet is not None and wallet.wallet_type == "Gift Card":
			description = f"Gift card {wallet.code_hint or ''} ({reservation.credit_line_id})"
		else:
			description = f"Store credit ({reservation.credit_line_id})"
		quotation.append(
			"taxes",
			{
				"charge_type": "Actual",
				"account_head": account,
				"description": description,
				"tax_amount": -flt(amount),
			},
		)

	@staticmethod
	def _deduction_account(company: str) -> str | None:
		"""Return the account credit deductions post to: the receivable account."""
		account = frappe.get_cached_value("Company", company, "default_receivable_account")
		if account:
			return account
		return frappe.db.get_value(
			"Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
		)

	@staticmethod
	def _open_reservations(quotation: "Document") -> list[dict]:
		"""Return the cart's open holds, oldest first (caps apply in order)."""
		return frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation.name, "status": "Reserved"},
			fields=["name", "credit_line_id", "wallet", "amount"],
			order_by="creation asc, name asc",
		)


def release_quotation_credit_holds(doc: "Document", method: str | None = None) -> None:
	"""Release a Quotation's open credit holds when it is cancelled or deleted.

	Hooked on ``Quotation`` ``on_cancel``/``on_trash`` (see ``ceto/hooks.py``):
	a hold must never outlive the payable it was booked against. Only this
	Quotation's open ``Reserved`` holds are flipped to ``Released``; a
	Quotation without holds — the overwhelmingly common case — costs one
	indexed SELECT. Reservations are Ceto-owned rows, so the release needs no
	permissions beyond the hook's direct write.
	"""
	for hold in frappe.get_all(
		"Ceto Cart Credit Reservation",
		filters={"quotation": doc.name, "status": "Reserved"},
		pluck="name",
	):
		CartCredits.release(hold)
