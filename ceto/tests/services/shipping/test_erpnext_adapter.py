"""Focused tests for the pure ERPNext Shipping Rule adapter."""

import unittest

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.erpnext_adapter import (
	NET_TOTAL,
	NET_WEIGHT,
	SELLING_RULE_TYPE,
	ShippingRuleCondition,
	ShippingRuleSet,
	is_eligible_rule,
	rule_amount,
)

COMPANY = "Ceto Adapter Co"
OTHER_COMPANY = "Other Co"


def context(**overrides) -> ShippingQuoteContext:
	values = {
		"cart_id": "cart_1",
		"company": COMPANY,
		"company_currency": "THB",
		"currency": "THB",
		"conversion_rate": 1.0,
		"base_net_total": 1500.0,
		"total_net_weight": 12.0,
	}
	values.update(overrides)
	return ShippingQuoteContext(**values)


def rule(**overrides) -> ShippingRuleSet:
	values = {
		"name": "Bracketed Rate",
		"label": "Bracketed Rate",
		"company": COMPANY,
		"disabled": False,
		"shipping_rule_type": SELLING_RULE_TYPE,
		"calculate_based_on": NET_TOTAL,
		"shipping_amount": 50.0,
		"conditions": (
			ShippingRuleCondition(0.0, 1000.0, 30.0),
			ShippingRuleCondition(1000.0, 0.0, 10.0),  # a zero to_value is open-ended
		),
		"countries": (),
	}
	values.update(overrides)
	return ShippingRuleSet(**values)


class TestRuleAmount(unittest.TestCase):
	def test_a_fixed_rule_serves_its_flat_amount(self) -> None:
		flat = rule(calculate_based_on="Fixed", conditions=(), shipping_amount=50.0)
		self.assertEqual(rule_amount(flat, context(base_net_total=0.0)), 50.0)

	def test_net_total_conditions_match_the_first_containing_row(self) -> None:
		self.assertEqual(rule_amount(rule(), context(base_net_total=500.0)), 30.0)
		# the inclusive upper bound matches exactly like ERPNext's scan
		self.assertEqual(rule_amount(rule(), context(base_net_total=1000.0)), 30.0)
		self.assertEqual(rule_amount(rule(), context(base_net_total=1000.01)), 10.0)

	def test_rows_scan_in_stored_order_not_in_bound_order(self) -> None:
		# ERPNext walks the rows as stored (its validate only renumbers
		# them), so an open-ended row first in order wins even below its
		# from value — the adapter mirrors the real scan, not a sorted one.
		unsorted = rule(
			conditions=(ShippingRuleCondition(1000.0, 0.0, 10.0), ShippingRuleCondition(0.0, 1000.0, 30.0))
		)
		self.assertEqual(rule_amount(unsorted, context(base_net_total=500.0)), 10.0)

	def test_no_matching_condition_defaults_to_zero(self) -> None:
		self.assertEqual(rule_amount(rule(conditions=()), context()), 0.0)
		narrow = rule(conditions=(ShippingRuleCondition(2000.0, 3000.0, 30.0),))
		self.assertEqual(rule_amount(narrow, context()), 0.0)

	def test_net_weight_conditions_price_the_weight(self) -> None:
		weight = rule(
			calculate_based_on=NET_WEIGHT,
			conditions=(ShippingRuleCondition(0.0, 10.0, 5.0), ShippingRuleCondition(10.0, 0.0, 2.0)),
		)
		self.assertEqual(rule_amount(weight, context(total_net_weight=12.0)), 2.0)
		self.assertEqual(rule_amount(weight, context(total_net_weight=0.0)), 5.0)

	def test_a_foreign_cart_currency_divides_by_the_conversion_rate(self) -> None:
		flat = rule(calculate_based_on="Fixed", conditions=(), shipping_amount=50.0)
		foreign = context(currency="EUR", company_currency="THB", conversion_rate=4.0)
		self.assertEqual(rule_amount(flat, foreign), 12.5)
		rounded = context(currency="EUR", company_currency="THB", conversion_rate=3.0)
		self.assertEqual(rule_amount(flat, rounded), 16.67)

	def test_the_same_currency_never_divides(self) -> None:
		flat = rule(calculate_based_on="Fixed", conditions=(), shipping_amount=50.0)
		same = context(currency="THB", company_currency="THB", conversion_rate=0.0)
		self.assertEqual(rule_amount(flat, same), 50.0)


class TestEligibility(unittest.TestCase):
	def test_enabled_selling_rules_of_the_company_are_eligible(self) -> None:
		self.assertTrue(is_eligible_rule(rule(), context()))

	def test_disabled_buying_and_foreign_rules_are_not(self) -> None:
		for broken in (
			rule(disabled=True),
			rule(shipping_rule_type="Buying"),
			rule(company=OTHER_COMPANY),
		):
			with self.subTest(broken=(broken.disabled, broken.shipping_rule_type, broken.company)):
				self.assertFalse(is_eligible_rule(broken, context()))

	def test_country_rules_price_the_shipping_country(self) -> None:
		us_rule = rule(countries=("United States",))
		self.assertTrue(is_eligible_rule(us_rule, context(country="United States")))
		self.assertFalse(is_eligible_rule(us_rule, context(country="India")))

	def test_an_addressless_cart_stays_eligible_like_erpnext(self) -> None:
		# ShippingRule.apply validates countries only when the document has
		# a shipping address; the listing keeps the exact behaviour.
		self.assertTrue(is_eligible_rule(rule(countries=("United States",)), context(country=None)))


if __name__ == "__main__":
	unittest.main()
