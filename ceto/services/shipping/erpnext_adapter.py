"""Pure read adapter over ERPNext ``Shipping Rule`` masters.

The adapter reproduces exactly what ERPNext's own ``ShippingRule.apply``
charges when the controllers apply a rule to a selling document — but as
a read: eligibility and the resolved rate are computed from preloaded
masters and the quote context, no document is touched, and the rule set
is fetched in a fixed number of batched queries (heads, conditions,
countries — three reads however many rules serve), so a listing can never
degrade into per-rule reads.

Eligibility mirrors the surfaces Ceto already applies options with
(:class:`ceto.services.carts.shipping.CartShippingMethods`) and the
controller's own application: the rule must be enabled, a ``Selling``
rule, and belong to the cart's company. A rule restricted to countries
applies only when the quote context carries a shipping-address country —
``ShippingRule.apply`` validates countries only when the document has a
shipping address — and the adapter keeps that exact behaviour, so a
listed option is never one ERPNext would refuse at apply time (and vice
versa).

The amount is the same resolution ``ShippingRule.apply`` performs:
``Fixed`` rules serve ``shipping_amount``; ``Net Total`` and ``Net
Weight`` rules walk their condition rows in stored row order — the same
order ``get_shipping_amount_from_rules`` walks (the doctype's validate
only renumbers rows, it never reorders them) — and the first row whose
open-ended or inclusive range contains the value wins, defaulting to 0.
A rate resolved in company currency is then divided by the document
conversion rate when the cart currency differs, rounded to two decimals
with ``flt`` — the same guard, formula and rounding, so the quote equals
the charge row the applied method books.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import frappe
from frappe.utils import flt

from ceto.services.shipping.context import ShippingQuoteContext

FIXED = "Fixed"
NET_TOTAL = "Net Total"
NET_WEIGHT = "Net Weight"
SELLING_RULE_TYPE = "Selling"

HEAD_FIELDS = (
	"name",
	"label",
	"company",
	"disabled",
	"shipping_rule_type",
	"calculate_based_on",
	"shipping_amount",
)


@dataclass(frozen=True, slots=True)
class ShippingRuleCondition:
	"""One ``Shipping Rule Condition`` row; a zero ``to_value`` is open-ended."""

	from_value: float
	to_value: float
	shipping_amount: float


@dataclass(frozen=True, slots=True)
class ShippingRuleSet:
	"""One rule master flattened with its child rows, read-only."""

	name: str
	label: str
	company: str
	disabled: bool
	shipping_rule_type: str
	calculate_based_on: str
	shipping_amount: float
	conditions: tuple[ShippingRuleCondition, ...] = ()
	countries: tuple[str, ...] = ()


def fetch_rule_sets(company: str) -> list[ShippingRuleSet]:
	"""Return the enabled ``Selling`` rules of ``company`` with their children.

	Three batched reads however many rules serve: the rule heads, then both
	child tables of every head at once.
	"""
	heads = frappe.get_all(
		"Shipping Rule",
		filters={"disabled": 0, "shipping_rule_type": SELLING_RULE_TYPE, "company": company},
		fields=HEAD_FIELDS,
		order_by="name asc",
	)
	if not heads:
		return []
	names = [head.name for head in heads]
	conditions: dict[str, list[ShippingRuleCondition]] = {name: [] for name in names}
	for row in frappe.get_all(
		"Shipping Rule Condition",
		filters={"parent": ["in", names]},
		fields=("parent", "from_value", "to_value", "shipping_amount"),
		order_by="parent asc, idx asc",
	):
		conditions[row.parent].append(
			ShippingRuleCondition(flt(row.from_value), flt(row.to_value), flt(row.shipping_amount))
		)
	countries: dict[str, list[str]] = {name: [] for name in names}
	for row in frappe.get_all(
		"Shipping Rule Country",
		filters={"parent": ["in", names]},
		fields=("parent", "country"),
		order_by="parent asc, idx asc",
	):
		countries[row.parent].append(row.country)
	return [
		ShippingRuleSet(
			name=head.name,
			label=head.label,
			company=head.company,
			disabled=bool(head.disabled),
			shipping_rule_type=head.shipping_rule_type,
			calculate_based_on=head.calculate_based_on,
			shipping_amount=flt(head.shipping_amount),
			conditions=tuple(conditions[head.name]),
			countries=tuple(countries[head.name]),
		)
		for head in heads
	]


def is_eligible_rule(rule: ShippingRuleSet, context: ShippingQuoteContext) -> bool:
	"""Return whether ERPNext would accept ``rule`` for ``context``'s cart."""
	if rule.disabled or rule.shipping_rule_type != SELLING_RULE_TYPE or rule.company != context.company:
		return False
	# ShippingRule.apply validates countries only when the document has a
	# shipping address, so a restricted rule stays eligible for an
	# addressless cart exactly as ERPNext would apply it.
	if rule.countries and context.country and context.country not in rule.countries:
		return False
	return True


def eligible_rules(
	rule_sets: Sequence[ShippingRuleSet], context: ShippingQuoteContext
) -> Iterator[ShippingRuleSet]:
	"""Yield the rules of ``rule_sets`` ERPNext would accept for ``context``."""
	return (rule for rule in rule_sets if is_eligible_rule(rule, context))


def rule_amount(rule: ShippingRuleSet, context: ShippingQuoteContext) -> float:
	"""Return the rate ``ShippingRule.apply`` books for ``rule`` on ``context``."""
	if rule.calculate_based_on == NET_TOTAL:
		amount = _amount_from_conditions(rule.conditions, context.base_net_total)
	elif rule.calculate_based_on == NET_WEIGHT:
		amount = _amount_from_conditions(rule.conditions, context.total_net_weight)
	else:
		amount = flt(rule.shipping_amount)
	# The rate resolves in the company currency; a foreign cart currency
	# gets the same division and two-decimal rounding the application does.
	if context.currency != context.company_currency:
		amount = flt(amount / context.conversion_rate, 2)
	return amount


def _amount_from_conditions(conditions: Sequence[ShippingRuleCondition], value: float) -> float:
	"""First condition whose range contains ``value`` — ERPNext's own scan.

	The rows are walked in stored row order, the order
	``ShippingRule.get_shipping_amount_from_rules`` walks them in: an
	open-ended row (a blank or zero ``to_value``) matches everything at or
	above its from value, and the first match wins.
	"""
	for condition in conditions:
		if not condition.to_value or flt(condition.from_value) <= flt(value) <= flt(condition.to_value):
			return flt(condition.shipping_amount)
	return 0.0
