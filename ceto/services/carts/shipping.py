"""Shipping domain service for Ceto carts.

ERPNext books a ``Shipping Rule`` charge as an ``Actual`` row in the
Quotation ``taxes`` table, keyed on charge type, account head and cost
center. Reading (:class:`CartShipping`) locates that row for the applied
rule; applying (:class:`CartShippingMethods`) validates the option, links
the Quotation's single ``shipping_rule`` and lets the ERPNext controllers
write the charge row on the save. Options are named either by the
shipping-options surface's opaque ``so_`` id — the built-in ``erpnext``
provider's tokens decode to their ``Shipping Rule`` option key — or by
the legacy raw rule name.

``amount`` is the row's ``tax_amount`` — the value the rule application
wrote, the one ERPNext's recalculation keeps for ``Actual`` rows, and the
one Ceto's empty-cart save baseline zeroes. ERPNext allocates no tax onto
the row, so the serialized ``tax_total`` is 0 and ``tax_amount`` serves as
both the ``shipping_*`` and ``original_shipping_*`` amounts.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems
from ceto.services.shipping.errors import MalformedShippingOptionIdError
from ceto.services.shipping.ids import OPTION_ID_PREFIX, decode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID

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
	def applied_charge(
		cls,
		quotation: "Document",
		*,
		rules: "dict[str, Document | dict | None] | None" = None,
	) -> "AppliedShippingCharge | None":
		"""Return the applied rule's ``Actual`` charge row, or ``None``.

		``None`` means there is no shipping to report: no rule linked, the
		rule master gone, or the charge row absent (an itemless cart — ERPNext
		never applies the rule there). The Quotation carries exactly one
		``shipping_rule`` link, so there is at most one such row.
		``rules`` is a preloaded rule-name → rule-fields map for bulk readers;
		a miss there behaves like a rule deleted from the master.
		"""
		rule = quotation.get("shipping_rule")
		if not rule:
			return None
		applied = (
			rules.get(rule)
			if rules is not None
			else frappe.db.get_value("Shipping Rule", rule, RULE_FIELDS, as_dict=True)
		)
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
	def applied_option_id(charge: "AppliedShippingCharge", reference: "Document") -> str:
		"""Return the public option id the applied method serializes.

		The apply records the supplied option id on the cart reference and
		the serializer echoes it back, so a method applied with the
		shipping-options surface's opaque ``so_`` id keeps that identity on
		the cart (list → calculate → add-to-cart). The echo only stands
		while it still names the linked rule: a reference without a usable
		record — carts predating the record, a rule linked outside the apply
		service — and a legacy raw name keep serving the raw rule name.
		"""
		supplied = (reference.get("shipping_option_id") or "").strip()
		if supplied == charge.rule:
			return charge.rule
		try:
			provider_id, option_key = decode_option_id(supplied)
		except MalformedShippingOptionIdError:
			return charge.rule
		if provider_id == PROVIDER_ID and option_key == charge.rule:
			return supplied
		return charge.rule

	@staticmethod
	def _charge_row(quotation: "Document", applied: "Document") -> "Document | None":
		"""Match the rule's ``Actual`` charge row the way ERPNext itself does.

		ERPNext keys the row on charge type, account head and cost center and
		keeps the last match; the rule label stamped into the row description
		is the stronger signal, so a label match wins when present.
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

	ERPNext applies the linked rule itself on every controller save, so
	applying a method only validates the option, detaches a charge row the
	controller cannot reuse, links the rule and persists through the shared
	cart save helper.
	"""

	@classmethod
	def apply(cls, quotation: "Document", option_id: str) -> None:
		"""Make ``option_id`` the cart's shipping method and persist the cart.

		``option_id`` names an eligible rule through the opaque ``so_``
		token of the built-in ``erpnext`` provider or through the legacy raw
		rule name. Runs inside the cart row lock; a failing option or a rule
		ERPNext rejects during the save (notably the shipping-address
		country eligibility check) raises before anything is committed and
		the caller's transaction rolls the attempt back. An itemless cart
		keeps the option link but produces no charge row, because ERPNext
		skips the rule application for itemless documents; the charge
		materializes on the next save that has lines.
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

		The apply keeps accepting the legacy raw ``Shipping Rule`` name
		beside the shipping-options contract's opaque ``so_`` ids: a
		well-formed token of the built-in ``erpnext`` provider decodes to
		its option key — the rule name — and resolves like the raw name, so
		every option the surface lists for a cart also applies. A malformed
		token and a foreign provider's token are ``UNKNOWN_OPTION`` like an
		unknown rule, keeping the option space opaque. Unknown, disabled,
		buying-side or foreign-company options are ``invalid_data``: the
		master exists but cannot be applied to this cart.
		"""
		try:
			rule = frappe.get_doc("Shipping Rule", _applied_rule_name(option_id))
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

		ERPNext rewrites the existing row in place only when both rules share
		account head and cost center; otherwise it would append a second
		charge row and count shipping twice. The row is matched and removed
		exactly the way ERPNext's own ``remove_shipping_charge`` matches it
		for the currently linked rule.
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


def _applied_rule_name(option_id: str) -> str:
	"""Decode ``option_id`` to the ``Shipping Rule`` name it applies.

	A non-``so_`` id is the legacy raw rule name and passes through. A
	well-formed ``so_`` token of the built-in ``erpnext`` provider decodes
	to its option key — the rule name the token was minted from. A
	malformed token and a foreign provider's token are ``UNKNOWN_OPTION``:
	the cart applies only the built-in rules the option surface serves.
	"""
	if not option_id.startswith(OPTION_ID_PREFIX):
		return option_id
	try:
		provider_id, option_key = decode_option_id(option_id)
	except MalformedShippingOptionIdError:
		raise InvalidDataError(UNKNOWN_OPTION) from None
	if provider_id != PROVIDER_ID:
		raise InvalidDataError(UNKNOWN_OPTION)
	return option_key
