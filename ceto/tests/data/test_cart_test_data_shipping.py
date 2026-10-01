"""Focused fixture tests for the Phase 4 shipping rules in ``cart_test_data``.

Pins the committed-fixture contracts the shipping tests rely on: instantiating
``CartTestData`` converges on the same Selling rules instead of duplicating
masters, each variant carries the state its scenario needs, and the rows
survive a rollback like the one the router performs on a failed request.
"""

import erpnext
import frappe

from ceto.tests.data.cart_test_data import (
	SHIPPING_COUNTRY_RATE_AMOUNT,
	SHIPPING_COUNTRY_RATE_LABEL,
	SHIPPING_DISABLED_RATE_LABEL,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite


def require_company(test: CetoTestSuite) -> None:
	"""Skip unless the site offers the commerce baseline a usable Company.

	Mirrors ``test_bootstrap_test_master_data.require_company``.
	"""
	if erpnext.get_default_company():
		return
	if len(frappe.get_all("Company", pluck="name")) == 1:
		return
	test.skipTest("No default or single Company; commerce baseline prerequisites are unavailable")


class TestCartShippingFixtures(CetoTestSuite):
	def test_shipping_fixtures_survive_a_router_rollback(self) -> None:
		require_company(self)

		masters = CartTestData()
		frappe.db.rollback()

		self.assertTrue(frappe.db.exists("Account", masters.shipping_account))
		for name in (masters.flat_rate_rule, masters.country_rate_rule, masters.disabled_rate_rule):
			self.assertTrue(frappe.db.exists("Shipping Rule", name), name)

	def test_shipping_rules_converge_on_reruns(self) -> None:
		require_company(self)

		first = CartTestData()
		second = CartTestData()

		self.assertEqual(second.shipping_account, first.shipping_account)
		self.assertEqual(second.shipping_cost_center, first.shipping_cost_center)
		self.assertEqual(second.flat_rate_rule, first.flat_rate_rule)
		self.assertEqual(second.country_rate_rule, first.country_rate_rule)
		self.assertEqual(second.disabled_rate_rule, first.disabled_rate_rule)
		for label in (SHIPPING_FLAT_RATE_LABEL, SHIPPING_COUNTRY_RATE_LABEL, SHIPPING_DISABLED_RATE_LABEL):
			# The label is the document identity, so a rerun can never duplicate a rule.
			self.assertEqual(frappe.db.count("Shipping Rule", {"label": label}), 1, label)

	def test_shipping_rules_match_the_expected_state(self) -> None:
		require_company(self)

		masters = CartTestData()

		expected = {
			masters.flat_rate_rule: {"disabled": 0, "shipping_amount": SHIPPING_FLAT_RATE_AMOUNT},
			masters.country_rate_rule: {"disabled": 0, "shipping_amount": SHIPPING_COUNTRY_RATE_AMOUNT},
			# The disabled variant never applies its amount; it only pins the rerun default.
			masters.disabled_rate_rule: {"disabled": 1, "shipping_amount": SHIPPING_FLAT_RATE_AMOUNT},
		}
		for name, expected_fields in expected.items():
			row = frappe.db.get_value(
				"Shipping Rule",
				name,
				[
					"shipping_rule_type",
					"calculate_based_on",
					"company",
					"account",
					"cost_center",
					*expected_fields,
				],
				as_dict=True,
			)
			self.assertEqual(row.shipping_rule_type, "Selling", name)
			self.assertEqual(row.calculate_based_on, "Fixed", name)
			self.assertEqual(row.company, masters.company, name)
			self.assertEqual(row.account, masters.shipping_account, name)
			self.assertEqual(row.cost_center, masters.shipping_cost_center, name)
			for fieldname, value in expected_fields.items():
				self.assertEqual(getattr(row, fieldname), value, name)

		self.assertEqual(
			[row.country for row in frappe.get_doc("Shipping Rule", masters.country_rate_rule).countries],
			[masters.shipping_country],
		)
		self.assertEqual(frappe.get_doc("Shipping Rule", masters.flat_rate_rule).countries or [], [])
		self.assertEqual(frappe.db.get_value("Account", masters.shipping_account, "company"), masters.company)
