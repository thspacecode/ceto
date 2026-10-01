"""Shipping domain service for Ceto carts (Phase 4 subset).

ERPNext implements a ``Shipping Rule`` charge as an ``Actual`` row in the
Quotation ``taxes`` table: ``ShippingRule.add_shipping_rule_to_tax_table``
appends or updates the row and ``SellingController.remove_shipping_charge``
looks the very same row up again by charge type, account and cost center.
This module reads that row off the cart's Quotation with the applied rule's
own attributes — label (stamped into the row description), account, cost
center — and exposes the ERPNext-calculated charge; no amount or tax is ever
derived here. The apply side (:class:`CartShippingMethods`) resolves a public
option id onto the Quotation's single ``shipping_rule`` link and lets the same
ERPNext controllers write the charge row on the controller save.

``amount`` is the row's ``tax_amount``: the value the rule application wrote
and the one ERPNext's recalculation keeps for ``Actual`` rows. It is also the
value Ceto's empty-cart save baseline zeroes, so a cart that lost its last
line reports the shipping charge as 0 instead of a stale rule amount.

Limitations, both inherent to the ERPNext row:

- ERPNext appends the shipping row last and its Selling taxes allocate no tax
  onto it, so there is no calculated tax-on-shipping to read; the serialized
  ``tax_total`` of the method is 0.
- The row's pre- and post-discount charges only diverge under a document-level
  Grand Total discount, which Ceto does not produce; ``tax_amount`` is
  therefore used for both the ``shipping_*`` and ``original_shipping_*``
  amounts.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems

if TYPE_CHECKING:
	from frappe.model.document import Document

RULE_FIELDS = ("label", "account", "cost_center")

UNKNOWN_OPTION = "Shipping option not found"
DISABLED_OPTION = "Shipping option is disabled"
NON_SELLING_OPTION = "Shipping option is not available for carts"
FOREIGN_OPTION = "Shipping option is not available for the cart's company"


@dataclass(frozen=True)
class AppliedShippingCharge:
	"""The ERPNext-calculated Shipping Rule charge on one Quotation."""

	rule: str
	label: str
	tax_row: "Document"
	amount: float


class CartShipping:
	"""Locate the Shipping Rule charge ERPNext calculated on a Quotation."""

	@classmethod
	def applied_charge(cls, quotation: "Document") -> "AppliedShippingCharge | None":
		"""Return the applied rule's ``Actual`` charge row, or ``None``.

		``None`` means "no shipping to report": the Quotation carries no rule,
		the rule master is gone, or its calculated charge row is absent (for
		example an itemless cart, where ERPNext never applies the rule). The
		Quotation carries exactly one ``shipping_rule`` link, so a document can
		hold at most one such charge row.
		"""
		rule = quotation.get("shipping_rule")
		if not rule:
			return None
		applied = frappe.db.get_value("Shipping Rule", rule, RULE_FIELDS, as_dict=True)
		if not applied:
			return None
		row = cls._charge_row(quotation, applied)
		if row is None:
			return None
		return AppliedShippingCharge(
			rule=rule,
			label=applied.label,
			tax_row=row,
			amount=flt(row.tax_amount),
		)

	@staticmethod
	def _charge_row(quotation: "Document", applied: "Document") -> "Document | None":
		"""Match the rule's ``Actual`` charge row the way ERPNext itself does.

		``add_shipping_rule_to_tax_table`` keys the row on charge type, account
		head and cost center, and ``remove_shipping_charge`` filters the same
		three columns and keeps the last record found. The rule label stamped
		into the row description is the stronger signal, so a label match wins
		when present; otherwise the last match is kept, like ERPNext.
		"""
		candidates = [
			row
			for row in quotation.get("taxes") or []
			if row.get("charge_type") == "Actual"
			and row.get("account_head") == applied.account
			and row.get("cost_center") == applied.cost_center
		]
		if not candidates:
			return None
		labelled = [row for row in candidates if row.get("description") == applied.label]
		return (labelled or candidates)[-1]


class CartShippingMethods:
	"""Resolve a public shipping option onto the cart's Quotation.

	ERPNext applies the linked rule itself on every controller save
	(``calculate_shipping_charges``), so applying a method only validates the
	option, detaches a charge row the controller cannot reuse, links the rule
	and persists through the shared cart save helper — the charge row, its
	amount and the totals are always ERPNext's own output.
	"""

	@classmethod
	def apply(cls, quotation: "Document", option_id: str) -> None:
		"""Make ``option_id`` the cart's shipping method and persist the cart.

		Called inside the cart row lock; a failing option (unknown, disabled,
		buying-side, foreign company) or a rule ERPNext rejects during the save
		(notably the shipping-address country eligibility check in
		``ShippingRule.validate_countries``) raises before anything is
		committed, and the caller's transaction rolls the attempt back.

		An itemless cart keeps the option link but produces no charge row,
		because ERPNext skips ``calculate_taxes_and_totals`` — and with it the
		rule application — for itemless documents; the charge materializes on
		the next save that has lines.
		"""
		rule = cls._resolve_rule(option_id, quotation.get("company"))
		cls._detach_unused_charge(quotation, rule)
		quotation.shipping_rule = rule.name
		try:
			CartLineItems.save(quotation)
		except frappe.ValidationError as exc:
			raise InvalidDataError(str(exc) or "Shipping option cannot be applied") from exc

	@staticmethod
	def _resolve_rule(option_id: str, company: str) -> "Document":
		"""Return the enabled ``Selling`` rule ``option_id`` names.

		The public option id **is** the ``Shipping Rule`` name (Phase 4 has no
		shipping-options listing yet). Options that are unknown, disabled,
		buying-side or owned by another company are ``invalid_data`` — the
		option exists as master data but cannot be applied to this cart.
		"""
		try:
			rule = frappe.get_doc("Shipping Rule", option_id)
		except frappe.DoesNotExistError:
			raise InvalidDataError(UNKNOWN_OPTION) from None
		if rule.disabled:
			raise InvalidDataError(DISABLED_OPTION)
		if rule.shipping_rule_type != "Selling":
			raise InvalidDataError(NON_SELLING_OPTION)
		if rule.company != company:
			raise InvalidDataError(FOREIGN_OPTION)
		return rule

	@staticmethod
	def _detach_unused_charge(quotation: "Document", rule: "Document") -> None:
		"""Drop the previous rule's charge row when ERPNext cannot reuse it.

		``add_shipping_rule_to_tax_table`` keys the charge row on charge type,
		account head and cost center: switching between rules that share both
		rewrites the existing row in place, while a rule with a different
		account or cost center would append a second charge row and count
		shipping twice on the cart. The row is matched — and the last match
		removed — exactly the way ERPNext's own ``remove_shipping_charge``
		matches it for the currently linked rule; recalculated totals are left
		to the controller save.
		"""
		previous = quotation.get("shipping_rule")
		if not previous or previous == rule.name:
			return
		stale = frappe.db.get_value("Shipping Rule", previous, ("account", "cost_center"), as_dict=True)
		if not stale or (stale.account == rule.account and stale.cost_center == rule.cost_center):
			return
		for row in reversed(quotation.get("taxes") or []):
			if (
				row.charge_type == "Actual"
				and row.account_head == stale.account
				and row.cost_center == stale.cost_center
			):
				quotation.remove(row)
				return
