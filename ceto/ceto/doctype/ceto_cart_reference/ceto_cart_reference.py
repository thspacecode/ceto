import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CetoCartReference(Document):
	"""Medusa identity and ownership data for a cart Quotation."""

	def validate(self) -> None:
		self._validate_quotation()
		self._validate_metadata()

	def on_trash(self) -> None:
		"""Explicitly clean up the cart's line item references on delete."""
		for name in frappe.get_all(
			"Ceto Cart Line Item Reference",
			filters={"cart_reference": self.name},
			pluck="name",
		):
			frappe.delete_doc("Ceto Cart Line Item Reference", name, ignore_permissions=True, force=True)
		for name in frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": self.quotation},
			pluck="name",
		):
			frappe.delete_doc("Ceto Cart Credit Reservation", name, ignore_permissions=True, force=True)

	def _validate_quotation(self) -> None:
		order_type, docstatus = frappe.db.get_value(
			"Quotation", self.quotation, ["order_type", "docstatus"]
		) or (None, None)
		if order_type != "Shopping Cart":
			frappe.throw(_("Cart reference must point to a Shopping Cart Quotation"))
		if cint(docstatus) != 0:
			frappe.throw(_("Cart reference must point to a draft Quotation"))

	def _validate_metadata(self) -> None:
		if not self.metadata:
			return
		try:
			value = json.loads(self.metadata)
		except (TypeError, ValueError):
			frappe.throw(_("Cart metadata must be valid JSON"))
		if not isinstance(value, dict):
			frappe.throw(_("Cart metadata must be a JSON object"))
