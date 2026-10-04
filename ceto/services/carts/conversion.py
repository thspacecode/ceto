"""Quotation -> Sales Order conversion for Ceto carts.

Thin, reusable wrapper around ERPNext's own mapper
(``erpnext.selling.doctype.quotation.quotation.make_sales_order``) so cart
completion never re-implements ERPNext mapping logic. The mapper copies the
cart's stored pricing — the mapped rows carry the Quotation's
``price_list_rate`` / discounts / ``rate`` and ERPNext's item-details pass
keeps already-set values — and ``_preserve_stored_pricing`` re-asserts those
stored values before the save, so a pricing-rule match or a price reload for
the Sales Order party can never move a rate between mapping and insert: the
placed order carries exactly the pricing the cart stored.
"""

from __future__ import annotations

import frappe
from erpnext.selling.doctype.quotation.quotation import make_sales_order
from frappe.model.document import Document
from frappe.utils import flt

#: Per-row pricing the placed order must keep from the cart Quotation.
STORED_PRICING_FIELDS = ("price_list_rate", "discount_percentage", "discount_amount", "rate")


def make_sales_order_from_quotation(quotation_name: str) -> Document:
	"""Map a submitted Quotation into an unsaved Sales Order (ERPNext mapper)."""
	return make_sales_order(quotation_name)


def convert_quotation_to_sales_order(quotation_name: str, *, submit: bool = False) -> Document:
	"""Create (and optionally submit) a Sales Order from a submitted Quotation."""
	sales_order = make_sales_order_from_quotation(quotation_name)
	_preserve_stored_pricing(quotation_name, sales_order)
	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	if submit:
		sales_order.submit()
	return sales_order


def _preserve_stored_pricing(quotation_name: str, sales_order: Document) -> None:
	"""Re-assert the cart Quotation's stored pricing on the mapped Sales Order.

	Completion promises the placed order to carry exactly the pricing the
	cart stored (Recorded Decision: preserve stored pricing). The mapper
	copies the stored row values, but ERPNext's item-details pass on the
	insert could still refill a field the mapper left empty; the stored
	values are therefore re-asserted per mapped row (matched through the
	mapper's ``quotation_item`` source-row link) and ERPNext recalculates
	the totals from them once.
	"""
	stored = {
		row.name: row
		for row in frappe.get_all(
			"Quotation Item",
			filters={"parent": quotation_name, "parenttype": "Quotation"},
			fields=["name", *STORED_PRICING_FIELDS],
		)
	}
	changed = False
	for row in sales_order.items or []:
		source = stored.get(row.get("quotation_item"))
		if source is None:
			continue
		for field in STORED_PRICING_FIELDS:
			value = flt(source.get(field))
			if flt(row.get(field)) != value:
				row.set(field, value)
				changed = True
	if changed:
		# One ERPNext controller pass derives the totals from the stored
		# pricing; nothing is recalculated by Ceto itself.
		sales_order.calculate_taxes_and_totals()
