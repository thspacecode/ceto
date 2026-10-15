"""Payment collection/session persistence behind the pinned contracts.

Ceto mirrors Medusa's checkout-shaped payment model on its own DocTypes:

- **One collection per cart.** ``Ceto Payment Collection`` is named by the
  stable public ``pay_col_…`` id and linked uniquely to the cart's
  ``Ceto Cart Reference`` — Medusa's create-collection route itself
  upserts (an existing cart collection is returned, never duplicated), so
  Ceto enforces the same invariant at the schema level. The collection's
  ``amount`` / ``currency_code`` track the cart's *current* payable.
- **Idempotent session creation.** ``Ceto Payment Session`` is named by
  the stable public ``payses_…`` id and snapshots the three keys payment
  creation is idempotent on — ``provider_id``, ``amount`` and
  ``currency_code`` — plus ``is_current``. Creating a session for the
  provider/cart pair that already matches the cart's current payable
  returns the collection's current session untouched; a changed amount,
  currency or provider makes the old session stale (``is_current`` 0)
  and books a fresh current session for the new payable. Only one
  current session may exist per collection (DocType-validated), while
  stale sessions stay as history rows.

Everything runs in the caller's transaction, and every payment writer
takes its row locks in one order — cart (route flows only) → collection →
session — so the paygi success webhook
(``ceto.services.payments.synchronization``), which holds no cart locks,
and a session recreation serialize on the collection row instead of
interleaving or deadlocking.
"""

import secrets
from dataclasses import dataclass
from typing import TYPE_CHECKING

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.payments.providers import PaymentProvider, ProviderRegistry, default_registry

if TYPE_CHECKING:
	from frappe.model.document import Document


def new_payment_collection_id() -> str:
	"""Return a stable public collection id: ``pay_col_`` + 128 crypto bits."""
	return f"pay_col_{secrets.token_hex(16)}"


def new_payment_session_id() -> str:
	"""Return a stable public session id: ``payses_`` + 128 crypto bits."""
	return f"payses_{secrets.token_hex(16)}"


@dataclass(frozen=True)
class CartPayable:
	"""The cart's current payable, as payment creation keys on it."""

	amount: float
	currency_code: str


class PaymentCollections:
	"""Create and resolve carts' payment collections and sessions."""

	@classmethod
	def current_collection(cls, cart_id: str) -> "Document | None":
		"""Return the cart's payment collection document, if one exists."""
		name = frappe.db.get_value("Ceto Payment Collection", {"cart_reference": cart_id}, "name")
		if not name:
			return None
		return frappe.get_doc("Ceto Payment Collection", name)

	@classmethod
	def lock_collection(cls, collection_name: str) -> None:
		"""Row-lock one collection: the lock every payment writer takes first.

		Route flows arrive holding the cart row locks and lock the
		collection before touching any session row; the webhook success (see
		:mod:`ceto.services.payments.synchronization`) holds no cart locks
		and locks this same pair in the same order. One order everywhere
		means capture and recreation serialize instead of deadlocking.
		"""
		table = frappe.qb.DocType("Ceto Payment Collection")
		frappe.qb.from_(table).select(table.name).where(table.name == collection_name).for_update().run()

	@classmethod
	def ensure_collection(cls, cart_id: str) -> "Document":
		"""Return the cart's payment collection, creating it when missing.

		The collection starts on the pinned ``not_paid`` status and carries
		the cart's current payable; a later ``ensure`` refreshes those two
		columns to the cart's current totals (the sessions carry the
		per-attempt snapshots).
		"""
		collection = cls.current_collection(cart_id)
		if collection is not None:
			return collection
		payable = cls._payable(cls._cart_reference(cart_id).quotation)
		return frappe.get_doc(
			{
				"doctype": "Ceto Payment Collection",
				"payment_collection_id": new_payment_collection_id(),
				"cart_reference": cart_id,
				"currency_code": payable.currency_code,
				"amount": payable.amount,
				"status": "not_paid",
			}
		).insert(ignore_permissions=True)

	@classmethod
	def current_session(cls, collection: "Document") -> "Document | None":
		"""Return the collection's current payment session, if any."""
		name = frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": collection.name, "is_current": 1},
			"name",
		)
		if not name:
			return None
		return frappe.get_doc("Ceto Payment Session", name)

	@classmethod
	def ensure_session(
		cls,
		cart_id: str,
		provider_id: str,
		*,
		registry: ProviderRegistry | None = None,
	) -> "Document":
		"""Return the cart's payment session for ``provider_id``, idempotently.

		The current session is reused exactly while its provider, amount and
		currency still match the cart's current payable and it is still
		``pending``. Anything else — a changed total, another provider, a
		session that left ``pending`` — is made stale (``is_current`` 0)
		and replaced by a fresh current session, so the returned session is
		always the collection's single live one. ``provider_id`` must
		resolve to an enabled provider in ``registry`` (the built-in
		registry, unless one is injected).

		The collection row is locked, and the rows the decision reads are
		re-read under that lock, before any session row is touched. The
		locking re-reads matter because plain reads answer from the
		transaction's snapshot, not the row's committed present: a webhook
		capture that committed while this flow waited for the lock must be
		seen here — a captured session is never handed out as reusable, and
		a collection it completed is reset instead of left completed behind
		an unpaid fresh session.
		"""
		cls._require_enabled_provider(provider_id, registry or default_registry())
		reference = cls._cart_reference(cart_id)
		payable = cls._payable(reference.quotation)
		collection = cls.ensure_collection(cart_id)
		cls.lock_collection(collection.name)
		collection.status = frappe.db.get_value(
			"Ceto Payment Collection", collection.name, "status", for_update=True
		)

		current = frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": collection.name, "is_current": 1},
			["name", "provider_id", "amount", "currency_code", "status"],
			as_dict=True,
			for_update=True,
		)
		if current is not None and cls._is_reusable(current, provider_id, payable):
			# The row is locked; nothing can change it before the insert
			# answers, so the caller may read the document plainly.
			return frappe.get_doc("Ceto Payment Session", current.name)
		if current is not None:
			cls._make_stale(current)
		cls._refresh_payable(collection, payable)
		return cls._insert_session(collection, payable, provider_id)

	@classmethod
	def _require_enabled_provider(cls, provider_id: str, registry: ProviderRegistry) -> PaymentProvider:
		provider = registry.resolve(provider_id)
		if provider is None:
			raise InvalidDataError(f"Unknown payment provider: {provider_id}")
		if not provider.is_enabled():
			raise InvalidDataError(f"Payment provider is not enabled: {provider_id}")
		return provider

	@staticmethod
	def _cart_reference(cart_id: str) -> "Document":
		"""Return the cart reference, masking unknown carts as not found."""
		name = frappe.db.get_value("Ceto Cart Reference", {"cart_id": cart_id}, "name")
		if not name:
			raise RouteNotFoundError("Cart not found")
		return frappe.get_doc("Ceto Cart Reference", name)

	@classmethod
	def _payable(cls, quotation_name: str) -> CartPayable:
		"""Return the cart Quotation's current payable (draft carts only).

		A submitted (or missing) Quotation means the cart has completed and
		is masked like every cart route does — payment sessions are only
		created for open carts.
		"""
		row = frappe.db.get_value(
			"Quotation",
			quotation_name,
			["grand_total", "currency", "docstatus"],
			as_dict=True,
		)
		if row is None or row.docstatus != 0:
			raise RouteNotFoundError("Cart not found")
		amount = flt(row.grand_total)
		if amount <= 0:
			raise InvalidDataError("Cart has no amount payable")
		return CartPayable(amount=amount, currency_code=str(row.currency).lower())

	@staticmethod
	def _is_reusable(current: "Document", provider_id: str, payable: CartPayable) -> bool:
		"""Whether ``current`` still answers for this payable and provider.

		Only a ``pending`` session is reusable; a session that left
		``pending`` (authorized or beyond) must not be silently handed out
		again for a new creation request.
		"""
		return (
			current.status == "pending"
			and current.provider_id == provider_id
			and flt(current.amount) == payable.amount
			and current.currency_code == payable.currency_code
		)

	@staticmethod
	def _make_stale(current: "Document") -> None:
		"""Flip the current session stale; it stays as a history row."""
		frappe.db.set_value("Ceto Payment Session", current.name, "is_current", 0)

	@staticmethod
	def _refresh_payable(collection: "Document", payable: CartPayable) -> None:
		"""Point the collection at the cart's current payable."""
		updates = {}
		if flt(collection.amount) != payable.amount:
			updates["amount"] = payable.amount
		if collection.currency_code != payable.currency_code:
			updates["currency_code"] = payable.currency_code
		if updates:
			frappe.db.set_value("Ceto Payment Collection", collection.name, updates)
			collection.reload()

	@staticmethod
	def _insert_session(collection: "Document", payable: CartPayable, provider_id: str) -> "Document":
		"""Book the fresh current session; the DocType re-checks uniqueness.

		A fresh session is an unpaid attempt by definition — a collection
		that had completed on a previous (now stale) session goes back to
		``not_paid`` so the stored status always answers for the collection's
		live session (the capture completes it again, exactly once).
		"""
		if collection.status != "not_paid":
			frappe.db.set_value("Ceto Payment Collection", collection.name, "status", "not_paid")
		return frappe.get_doc(
			{
				"doctype": "Ceto Payment Session",
				"payment_session_id": new_payment_session_id(),
				"payment_collection": collection.name,
				"provider_id": provider_id,
				"amount": payable.amount,
				"currency_code": payable.currency_code,
				"status": "pending",
				"is_current": 1,
			}
		).insert(ignore_permissions=True)
