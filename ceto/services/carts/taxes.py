"""Tax-template and totals services for Ceto carts.

Every Quotation save runs ERPNext's ``calculate_taxes_and_totals``, so
totals are always ERPNext's own output. Two cart operations need more than
that passive pass: the explicit recalculation endpoint
(:meth:`CartTaxes.recalculate`), and cart configuration changes that move
the ``Sales Taxes and Charges Template`` (:meth:`CartTaxes.refresh_template`
— ERPNext loads template rows only while the taxes table is empty, so
switching the link alone would keep pricing the cart with the previous
template's rows).
"""

from typing import TYPE_CHECKING

import frappe
from erpnext.controllers.accounts_controller import get_taxes_and_charges

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems

if TYPE_CHECKING:
	from frappe.model.document import Document

TEMPLATE_DOCTYPE = "Sales Taxes and Charges Template"


class CartTaxes:
	"""Totals and tax-template operations on the Quotation backing a cart."""

	@classmethod
	def recalculate(cls, quotation: "Document") -> None:
		"""Recalculate the cart's taxes and totals through ERPNext and save it.

		The recalculation **is** ERPNext's ``calculate_taxes_and_totals``
		followed by the shared cart save, so repeating the request reproduces
		the same numbers instead of accumulating anything. An itemless cart
		keeps the empty-cart baseline: ERPNext skips the calculation for
		documents without lines and the save helper zeroes the summary fields.
		"""
		quotation.calculate_taxes_and_totals()
		CartLineItems.save(quotation)

	@classmethod
	def refresh_template(cls, quotation: "Document", template: str | None) -> None:
		"""Point the cart at ``template``, reloading its rows on change.

		The same template keeps the cart's child-row identities and calculated
		amounts untouched. On a change, the taxes table is reloaded through
		ERPNext's own loader instead of being left with the previous
		template's rows; the selected Shipping Rule survives because only its
		charge row lived in the replaced table — the ``shipping_rule`` link
		stays on the Quotation and the caller's save reapplies the rule
		exactly once. Missing or disabled templates are rejected before any
		row is touched, so a bad region mapping cannot mutate the cart.
		"""
		if quotation.taxes_and_charges == template:
			return
		cls._validate_template(template)
		rows = cls._template_rows(template)
		quotation.taxes_and_charges = template
		quotation.set("taxes", rows)

	@staticmethod
	def _validate_template(template: str | None) -> None:
		"""Reject a disabled template before mutating the cart.

		Mirrors ERPNext's ``validate_enabled_taxes_and_charges`` but runs
		eagerly, so a disabled template fails as ``invalid_data`` instead of
		surfacing as a controller error after the rows were replaced.
		"""
		if template and frappe.get_cached_value(TEMPLATE_DOCTYPE, template, "disabled"):
			raise InvalidDataError(f"Sales Taxes and Charges Template '{template}' is disabled")

	@staticmethod
	def _template_rows(template: str | None) -> list[dict]:
		"""Return ``template``'s rows through ERPNext's own loader.

		``get_taxes_and_charges`` raises ``DoesNotExistError`` for a missing
		master; the cart maps that to ``invalid_data`` because the template is
		configuration of this cart, not a missing resource.
		"""
		if not template:
			return []
		try:
			return get_taxes_and_charges(TEMPLATE_DOCTYPE, template) or []
		except frappe.DoesNotExistError:
			raise InvalidDataError(f"Cart tax template not found: {template}") from None
