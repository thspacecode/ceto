"""Tax-template and totals services for Ceto carts.

ERPNext prices a cart through its Quotation: every controller save runs
``calculate_taxes_and_totals``, so totals are always ERPNext's own output.
Two cart operations need more than that passive pass:

- Medusa's ``POST /store/carts/{id}/taxes`` asks for an explicit
  recalculation; :meth:`CartTaxes.recalculate` runs the same ERPNext
  calculation and persists the Quotation.
- The cart configuration (region/sales channel) can resolve to a different
  ``Sales Taxes and Charges Template``. ERPNext's ``set_missing_values``
  loads template rows only while the taxes table is empty, so switching the
  ``taxes_and_charges`` link alone would keep pricing the cart with the
  previous template's rows; :meth:`CartTaxes.refresh_template` reloads the
  rows with ERPNext's own loader instead.
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

		The recalculation **is** ERPNext's ``calculate_taxes_and_totals`` —
		the controller pass every Quotation save runs, Shipping Rule
		application included — followed by the shared cart save. ERPNext
		recomputes every summary field from the rows, so repeating the
		request reproduces the same numbers instead of accumulating
		anything; an itemless cart keeps the empty-cart baseline (ERPNext
		skips the calculation for documents without lines and the save
		helper zeroes the summary fields).
		"""
		quotation.calculate_taxes_and_totals()
		CartLineItems.save(quotation)

	@classmethod
	def refresh_template(cls, quotation: "Document", template: str | None) -> None:
		"""Point the cart at ``template``, reloading its rows on change.

		A cart that keeps the same template keeps its rows: the child-row
		identities and the ERPNext-calculated amounts survive untouched, so
		configuration changes that do not move the template (a sales
		channel switch, the same region re-submitted) churn nothing.

		When the template changes, the taxes table is reloaded with ERPNext's
		own loader (:func:`get_taxes_and_charges`) rather than left holding
		the previous template's rows. The selected Shipping Rule survives
		the reload: its ``Actual`` charge row lived inside the replaced
		table, the ``shipping_rule`` link stays on the Quotation, and the
		caller's controller save reapplies the rule — exactly once, because
		``ShippingRule.add_shipping_rule_to_tax_table`` appends its charge
		row only when no row for the rule's account and cost center exists.
		An itemless cart defers the application to the next save that has
		lines, like every other rule application.

		Missing or disabled templates are rejected before any row is
		touched, so a bad region mapping cannot mutate the cart; deeper
		controller validation on the caller's save (and the transaction
		rollback that follows it) still applies.
		"""
		if quotation.taxes_and_charges == template:
			return
		cls._validate_template(template)
		rows = cls._template_rows(template)
		quotation.taxes_and_charges = template
		quotation.set("taxes", rows)

	@staticmethod
	def _validate_template(template: str | None) -> None:
		"""Reject a template the controllers would refuse, before mutating.

		Mirrors ERPNext's ``validate_enabled_taxes_and_charges`` (same wording,
		so either check reads the same to the storefront), but runs eagerly so
		a disabled template fails as ``invalid_data`` instead of surfacing as
		a controller error after the rows were replaced.
		"""
		if template and frappe.get_cached_value(TEMPLATE_DOCTYPE, template, "disabled"):
			raise InvalidDataError(f"Sales Taxes and Charges Template '{template}' is disabled")

	@staticmethod
	def _template_rows(template: str | None) -> list[dict]:
		"""Return ``template``'s rows through ERPNext's own loader.

		``get_taxes_and_charges`` raises ``DoesNotExistError`` for a missing
		master; the cart maps that to ``invalid_data`` — the template is
		configuration of this cart, not a missing resource — so the router
		answers 400 instead of masking the cart as not found.
		"""
		if not template:
			return []
		try:
			return get_taxes_and_charges(TEMPLATE_DOCTYPE, template) or []
		except frappe.DoesNotExistError:
			raise InvalidDataError(f"Cart tax template not found: {template}") from None
