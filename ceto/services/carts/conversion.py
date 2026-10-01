"""Quotation -> Sales Order conversion for Ceto carts.

Thin, reusable wrapper around ERPNext's own mapper
(``erpnext.selling.doctype.quotation.quotation.make_sales_order``) so cart
completion never re-implements ERPNext mapping logic.
"""

from __future__ import annotations

from erpnext.selling.doctype.quotation.quotation import make_sales_order
from frappe.model.document import Document


def make_sales_order_from_quotation(quotation_name: str) -> Document:
	"""Map a submitted Quotation into an unsaved Sales Order (ERPNext mapper)."""
	return make_sales_order(quotation_name)


def convert_quotation_to_sales_order(quotation_name: str, *, submit: bool = False) -> Document:
	"""Create (and optionally submit) a Sales Order from a submitted Quotation."""
	sales_order = make_sales_order_from_quotation(quotation_name)
	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	if submit:
		sales_order.submit()
	return sales_order
