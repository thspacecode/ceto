import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

#: The pinned ``PaymentSessionStatus`` values (pinned baseline of
#: ``@medusajs/types@2.21.1``); the Select field carries the same list.
STATUSES = (
	"pending",
	"pending_authorization",
	"authorized",
	"captured",
	"requires_more",
	"error",
	"canceled",
)


class CetoPaymentSession(Document):
	"""One provider payment attempt on a Ceto payment collection.

	Named by the stable public ``payses_…`` id the store API serves. The
	session snapshots the payable (``amount`` + ``currency_code``) and the
	``provider_id`` it was created for — idempotent creation returns the
	collection's current session when all three still match the cart, and
	a changed amount, currency or provider makes the old session stale
	(``is_current`` 0) so a fresh current session is required. Only one
	current session may exist per collection.
	"""

	def validate(self) -> None:
		self._validate_amount()
		self._validate_currency_code()
		self._validate_status()
		self._validate_provider_data()
		self._validate_single_current_session()

	def _validate_amount(self) -> None:
		if flt(self.amount) <= 0:
			frappe.throw(_("Payment session amount must be positive"))

	def _validate_currency_code(self) -> None:
		code = (self.currency_code or "").strip().lower()
		if len(code) != 3 or not code.isalpha():
			frappe.throw(_("Payment session currency code must be a 3-letter ISO 4217 code"))
		if code != self.currency_code:
			self.currency_code = code

	def _validate_status(self) -> None:
		if self.status not in STATUSES:
			frappe.throw(_("Unknown payment session status: {0}").format(self.status))

	def _validate_provider_data(self) -> None:
		if not self.provider_data:
			return
		try:
			value = json.loads(self.provider_data)
		except (TypeError, ValueError):
			frappe.throw(_("Payment session provider data must be valid JSON"))
		if not isinstance(value, dict):
			frappe.throw(_("Payment session provider data must be a JSON object"))

	def _validate_single_current_session(self) -> None:
		if not self.is_current:
			return
		current = frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": self.payment_collection, "is_current": 1, "name": ("!=", self.name)},
			"name",
		)
		if current:
			frappe.throw(
				_("Payment collection {0} already has a current payment session ({1})").format(
					self.payment_collection, current
				)
			)
