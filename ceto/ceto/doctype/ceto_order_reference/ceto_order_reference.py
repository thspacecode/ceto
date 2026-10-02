import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint


class CetoOrderReference(Document):
	"""Medusa order identity of a completed cart.

	One record per completion: the public ``order_id`` names the document,
	the ``sales_order`` is the ERPNext identity it stands for, and
	``cart_id`` keeps the completed cart's public id so the complete route
	can replay the order. Completed carts are otherwise unreachable — their
	Quotation has left the draft state every cart route requires — so the
	replay lookup by ``cart_id`` is the only way back to the order.

	Validate pins the record to a *real* completion: the referenced Sales
	Order must be submitted and must descend from the cart's Quotation
	(every mapped row points back at it), and the cart must actually have
	completed — its Quotation submitted.
	"""

	def validate(self) -> None:
		quotation = self._validate_completed_cart()
		self._validate_sales_order(quotation)

	def _validate_completed_cart(self) -> str:
		"""Require a cart that actually completed; return its Quotation.

		The referenced ``Ceto Cart Reference`` must exist and its Quotation
		must have been submitted: an open cart has not completed yet, and a
		cancelled one never will.
		"""
		quotation = frappe.db.get_value("Ceto Cart Reference", self.cart_id, "quotation")
		if quotation is None:
			frappe.throw(_("Order reference must point to an existing cart"))
		if cint(frappe.db.get_value("Quotation", quotation, "docstatus")) != 1:
			frappe.throw(_("Order reference must point to a completed cart"))
		return quotation

	def _validate_sales_order(self, quotation: str) -> None:
		"""Require the cart's own, submitted Sales Order.

		A draft order has not been placed yet, an unknown one names nothing,
		and a Sales Order whose rows do not descend from the cart's Quotation
		was never produced by this cart — the completion flow maps the
		submitted Quotation through ERPNext's own mapper, which stamps every
		mapped row with its source row (``prevdoc_docname``).
		"""
		docstatus = frappe.db.get_value("Sales Order", self.sales_order, "docstatus")
		if docstatus is None:
			frappe.throw(_("Order reference must point to an existing Sales Order"))
		if cint(docstatus) != 1:
			frappe.throw(_("Order reference must point to a submitted Sales Order"))
		self._validate_sales_order_lineage(quotation)

	def _validate_sales_order_lineage(self, quotation: str) -> None:
		rows = frappe.get_all(
			"Sales Order Item",
			filters={"parent": self.sales_order, "parenttype": "Sales Order"},
			pluck="prevdoc_docname",
		)
		if not rows or any(row != quotation for row in rows):
			frappe.throw(_("Order reference must point to a Sales Order created from the cart's Quotation"))
