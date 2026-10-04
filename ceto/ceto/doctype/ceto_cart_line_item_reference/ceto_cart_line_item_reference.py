import json

import frappe
from frappe import _
from frappe.model.document import Document


class CetoCartLineItemReference(Document):
	"""Medusa identity and metadata for one Quotation Item row of a cart."""

	def validate(self) -> None:
		self._validate_cart_reference()
		self._validate_quotation_item()
		self._validate_metadata()

	def _validate_cart_reference(self) -> None:
		reference_quotation = frappe.db.get_value("Ceto Cart Reference", self.cart_reference, "quotation")
		if reference_quotation != self.quotation:
			frappe.throw(_("Line item reference must point to the cart reference's Quotation"))

	def _validate_quotation_item(self) -> None:
		exists = frappe.db.exists("Quotation Item", {"name": self.quotation_item, "parent": self.quotation})
		if not exists:
			frappe.throw(_("Line item reference must point to a row of the linked Quotation"))

	def _validate_metadata(self) -> None:
		if not self.metadata:
			return
		try:
			value = json.loads(self.metadata)
		except (TypeError, ValueError):
			frappe.throw(_("Line item metadata must be valid JSON"))
		if not isinstance(value, dict):
			frappe.throw(_("Line item metadata must be a JSON object"))
