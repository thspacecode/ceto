import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

#: The pinned ``PaymentCollectionStatus`` values (pinned baseline of
#: ``@medusajs/types@2.21.1``); the Select field carries the same list.
STATUSES = ("not_paid", "awaiting", "authorized", "partially_authorized", "canceled", "completed", "failed")


class CetoPaymentCollection(Document):
	"""Ceto payment collection for one cart (Medusa ``PaymentCollection``).

	Named by the stable public ``pay_col_…`` id the store API serves. One
	collection covers a cart's whole payment life — the cart link is
	unique, mirroring Medusa's own upsert semantics of returning the
	existing collection for a cart — while ``currency_code`` / ``amount``
	track the cart's current payable and the sessions on the collection
	carry the per-attempt snapshot idempotent session creation keys on.
	"""

	def validate(self) -> None:
		self._validate_amount()
		self._validate_currency_code()
		self._validate_status()

	def _validate_amount(self) -> None:
		if flt(self.amount) < 0:
			frappe.throw(_("Payment collection amount must not be negative"))

	def _validate_currency_code(self) -> None:
		code = (self.currency_code or "").strip().lower()
		if len(code) != 3 or not code.isalpha():
			frappe.throw(_("Payment collection currency code must be a 3-letter ISO 4217 code"))
		if code != self.currency_code:
			self.currency_code = code

	def _validate_status(self) -> None:
		if self.status not in STATUSES:
			frappe.throw(_("Unknown payment collection status: {0}").format(self.status))
