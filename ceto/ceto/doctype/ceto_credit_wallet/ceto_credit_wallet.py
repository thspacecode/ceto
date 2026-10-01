import re

import frappe
from frappe.model.document import Document
from frappe.utils import flt

_CODE_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")
# A masked display hint only: a short prefix and suffix around a 4-8
# asterisk mask (``GC-****-1234``). The bound segments and the restricted
# charset keep the hint a display fragment — too short to carry a plaintext
# code, with no whitespace, control characters or markup — so serializing it
# into a cart response or a Quotation tax-row description can never leak the
# code or smuggle arbitrary text.
_CODE_HINT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{0,8}\*{4,8}[A-Za-z0-9_-]{0,8}$")


class CetoCreditWallet(Document):
	"""Provider-backed gift-card / store-credit ledger account.

	One wallet holds the balance a loyalty provider backs for one company,
	customer and currency. Gift-card codes are stored hash-only next to a
	display hint; the plaintext code never reaches the database. The company
	scaling is part of both uniqueness rules, so the same code or customer can
	hold separate wallets per company.
	"""

	def validate(self) -> None:
		self._validate_code()
		self._validate_wallet_identity()
		self._validate_uniqueness()
		self._validate_balance()

	def _validate_code(self) -> None:
		"""Normalize the hash-only code fields and keep them paired."""
		if self.code_hash:
			self.code_hash = self.code_hash.strip().lower()
			if not _CODE_HASH_PATTERN.fullmatch(self.code_hash):
				frappe.throw("Code hash must be a 64-character lowercase SHA-256 hex digest")
		if self.code_hint is not None:
			self.code_hint = self.code_hint.strip()
			if not _CODE_HINT_PATTERN.fullmatch(self.code_hint):
				frappe.throw("Code hint must be a masked display form like GC-****-1234")
		if bool(self.code_hash) != bool(self.code_hint):
			frappe.throw("Code hash and code hint must be set together")
		if self.wallet_type == "Gift Card" and not self.code_hash:
			frappe.throw("Gift card wallets must carry a code hash and a code hint")

	def _validate_wallet_identity(self) -> None:
		"""A store-credit wallet is owned by a customer or claimable by code."""
		if self.wallet_type == "Store Credit" and not self.customer and not self.code_hash:
			frappe.throw("Store credit wallets must carry a customer or a claim code")

	def _validate_uniqueness(self) -> None:
		"""Company scoping: a code and a customer wallet exist once per company."""
		if self.code_hash and frappe.db.exists(
			"Ceto Credit Wallet",
			{"company": self.company, "code_hash": self.code_hash, "name": ("!=", self.name)},
		):
			frappe.throw(f"A wallet with this code already exists for company {self.company}")
		if (
			self.wallet_type == "Store Credit"
			and self.customer
			and frappe.db.exists(
				"Ceto Credit Wallet",
				{
					"company": self.company,
					"currency": self.currency,
					"customer": self.customer,
					"name": ("!=", self.name),
					"wallet_type": "Store Credit",
				},
			)
		):
			frappe.throw(
				f"Customer {self.customer} already has a store credit wallet"
				f" in {self.currency} for company {self.company}"
			)

	def _validate_balance(self) -> None:
		if flt(self.credit_total) < 0 or flt(self.debit_total) < 0:
			frappe.throw("Credit and debit totals must not be negative")
		self.balance = flt(self.credit_total) - flt(self.debit_total)
		if self.balance < 0:
			frappe.throw("Balance must not be negative")
