"""Focused tests for the built-in ERPNext shipping provider on real masters.

Runs against the committed ``Shipping Rule`` fixtures and real cart
Quotations: every parity assertion compares the provider's quote with the
charge ERPNext itself books when the same rule is applied to the same
cart — through the controllers' save-time application or
``ShippingRule.apply`` on the live document — so the adapter cannot drift
from the real application without the suite failing.
"""

from dataclasses import FrozenInstanceError
from unittest import mock

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.quotation import CartService
from ceto.services.carts.shipping import CartShipping
from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.errors import MalformedShippingOptionIdError
from ceto.services.shipping.ids import decode_option_id, encode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID, ErpnextShippingRuleProvider
from ceto.services.shipping.registry import ShippingProviderRegistry
from ceto.tests.data.cart_test_data import (
	SHIPPING_COUNTRY_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreAddCartLineItem, StoreCreateCart

BRACKET_BELOW_AMOUNT = 40.0
BRACKET_ABOVE_AMOUNT = 12.0
WEIGHT_AMOUNT = 7.0


class TestErpnextShippingProvider(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier module's committed cart leaves its guest-linked
		# temporary Address behind; discard it so addressless carts inherit
		# nothing (the same guard the cart shipping serialization suite uses).
		self.masters.discard_committed_cart_temporaries()
		self.service = CartService()

	def _cart_with_line(self, **create_kwargs) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart(**create_kwargs))
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _link_rule(self, reference, rule: str) -> tuple:
		"""Link ``rule`` on the Quotation and let ERPNext apply the charge."""
		_reference, quotation = self.service.retrieve(reference.cart_id)
		quotation.shipping_rule = rule
		CartLineItems.save(quotation)
		return self.service.retrieve(reference.cart_id)

	def _condition_rule(self, label: str, boundary: float) -> str:
		"""Create an uncommitted two-bracket ``Net Total`` rule around ``boundary``."""
		return (
			frappe.get_doc(
				{
					"doctype": "Shipping Rule",
					"label": label,
					"shipping_rule_type": "Selling",
					"company": self.masters.company,
					"account": self.masters.shipping_account,
					"cost_center": self.masters.shipping_cost_center,
					"calculate_based_on": "Net Total",
					"conditions": [
						{"from_value": 0, "to_value": boundary, "shipping_amount": BRACKET_BELOW_AMOUNT},
						{"from_value": boundary, "to_value": 0, "shipping_amount": BRACKET_ABOVE_AMOUNT},
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_the_provider_serves_the_company_selling_rules(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)

		quotes = ErpnextShippingRuleProvider().list_options(context)
		by_key = {q.option_key: q for q in quotes}

		# Every enabled Selling rule of the cart's company serves; the
		# disabled fixture never does.
		self.assertIn(self.masters.flat_rate_rule, by_key)
		self.assertIn(self.masters.country_rate_rule, by_key)
		self.assertNotIn(self.masters.disabled_rate_rule, by_key)
		self.assertEqual([q.option_key for q in quotes], sorted(q.option_key for q in quotes))

		flat = by_key[self.masters.flat_rate_rule]
		self.assertEqual(flat.provider_id, PROVIDER_ID)
		self.assertEqual(flat.name, SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(flat.amount, SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(flat.currency, quotation.currency)
		self.assertEqual(flat.price_type, "flat")
		self.assertFalse(flat.is_tax_inclusive)
		self.assertIsNone(flat.data)
		self.assertIsNone(flat.metadata)
		self.assertEqual(flat.option_id, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule))

	def test_a_quote_matches_the_charge_erpnext_books(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)
		flat = next(
			q
			for q in ErpnextShippingRuleProvider().list_options(context)
			if q.option_key == self.masters.flat_rate_rule
		)

		# The real application: link the rule and let the controllers book
		# the Actual charge row on the save.
		reference, quotation = self._link_rule(reference, self.masters.flat_rate_rule)

		self.assertEqual(flat.amount, CartShipping.applied_charge(quotation).amount)
		self.assertEqual(flat.amount, SHIPPING_FLAT_RATE_AMOUNT)

	def test_conditioned_rules_match_the_erpnext_application(self) -> None:
		reference, quotation = self._cart_with_line()
		net_total = flt(quotation.base_net_total)
		below = self._condition_rule("Ceto Test Bracketed At Total", net_total)
		above = self._condition_rule("Ceto Test Bracketed Past Total", net_total - 1)

		for bracket_rule, expected in ((below, BRACKET_BELOW_AMOUNT), (above, BRACKET_ABOVE_AMOUNT)):
			reference, quotation = self._cart_with_line()
			context = ShippingQuoteContext.from_cart(reference, quotation)
			quote = next(
				q for q in ErpnextShippingRuleProvider().list_options(context) if q.option_key == bracket_rule
			)

			reference, quotation = self._link_rule(reference, bracket_rule)

			self.assertEqual(quote.amount, expected)
			self.assertEqual(quote.amount, CartShipping.applied_charge(quotation).amount)

	def test_weighted_rules_match_the_erpnext_application(self) -> None:
		# The bootstrap items carry no net weight, so the cart's
		# total_net_weight is 0 and the single open-ended row serves.
		weight_rule = (
			frappe.get_doc(
				{
					"doctype": "Shipping Rule",
					"label": "Ceto Test Weight Rate",
					"shipping_rule_type": "Selling",
					"company": self.masters.company,
					"account": self.masters.shipping_account,
					"cost_center": self.masters.shipping_cost_center,
					"calculate_based_on": "Net Weight",
					"conditions": [{"from_value": 0, "to_value": 0, "shipping_amount": WEIGHT_AMOUNT}],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)
		quote = next(
			q for q in ErpnextShippingRuleProvider().list_options(context) if q.option_key == weight_rule
		)

		reference, quotation = self._link_rule(reference, weight_rule)

		self.assertEqual(quote.amount, WEIGHT_AMOUNT)
		self.assertEqual(quote.amount, CartShipping.applied_charge(quotation).amount)

	def test_a_foreign_cart_currency_matches_the_erpnext_conversion(self) -> None:
		reference, quotation = self._cart_with_line()
		# In-memory currency override (never saved): the cart flow pins the
		# conversion at 1, so the parity comparison overrides both sides.
		quotation.currency = "EUR"
		quotation.conversion_rate = 4.0
		self.assertNotEqual(quotation.company_currency, "EUR")
		context = ShippingQuoteContext.from_cart(reference, quotation)

		flat = next(
			q
			for q in ErpnextShippingRuleProvider().list_options(context)
			if q.option_key == self.masters.flat_rate_rule
		)

		# ERPNext's own application on the same document state: the
		# controller sets the link, then ShippingRule.apply writes the row.
		quotation.shipping_rule = self.masters.flat_rate_rule
		frappe.get_doc("Shipping Rule", self.masters.flat_rate_rule).apply(quotation)

		self.assertEqual(flat.amount, CartShipping.applied_charge(quotation).amount)
		self.assertEqual(flat.amount, 12.5)

	def test_country_rules_follow_the_shipping_address(self) -> None:
		reference, quotation = self._cart_with_line(
			shipping_address={"country_code": "US", "address_1": "1 Main St", "city": "New York"}
		)
		context = ShippingQuoteContext.from_cart(reference, quotation)
		self.assertEqual(context.country, self.masters.shipping_country)
		keys = {q.option_key for q in ErpnextShippingRuleProvider().list_options(context)}
		self.assertIn(self.masters.flat_rate_rule, keys)
		self.assertIn(self.masters.country_rate_rule, keys)

		foreign, quotation = self._cart_with_line(
			shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
		)
		foreign_context = ShippingQuoteContext.from_cart(foreign, quotation)
		self.assertEqual(foreign_context.country, "India")
		keys = {q.option_key for q in ErpnextShippingRuleProvider().list_options(foreign_context)}
		self.assertIn(self.masters.flat_rate_rule, keys)
		self.assertNotIn(self.masters.country_rate_rule, keys)

	def test_a_country_eligible_quote_matches_the_erpnext_charge(self) -> None:
		reference, quotation = self._cart_with_line(
			shipping_address={"country_code": "US", "address_1": "1 Main St", "city": "New York"}
		)
		context = ShippingQuoteContext.from_cart(reference, quotation)
		quote = next(
			q
			for q in ErpnextShippingRuleProvider().list_options(context)
			if q.option_key == self.masters.country_rate_rule
		)

		reference, quotation = self._link_rule(reference, self.masters.country_rate_rule)

		self.assertEqual(quote.amount, CartShipping.applied_charge(quotation).amount)
		self.assertEqual(quote.amount, SHIPPING_COUNTRY_RATE_AMOUNT)

	def test_the_listing_batches_its_reads(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)

		recorded = []
		original = frappe.get_all

		def recorder(doctype, **kwargs):
			recorded.append(doctype)
			return original(doctype, **kwargs)

		with mock.patch("frappe.get_all", side_effect=recorder):
			ErpnextShippingRuleProvider().list_options(context)

		# Fixed reads however many rules serve: heads, conditions, countries.
		self.assertEqual(recorded, ["Shipping Rule", "Shipping Rule Condition", "Shipping Rule Country"])

	def test_the_provider_never_mutates_the_cart(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)
		before = frappe.as_json(quotation.as_dict())

		ErpnextShippingRuleProvider().list_options(context)
		ShippingProviderRegistry.from_site().list_options(context)

		self.assertEqual(frappe.as_json(quotation.as_dict()), before)

	def test_the_site_registry_resolves_pinned_option_ids(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)
		registry = ShippingProviderRegistry.from_site()

		# The test site registers no ceto_shipping_providers hook: the
		# built-in provider is the whole registry.
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID])

		flat = next(q for q in registry.list_options(context) if q.option_key == self.masters.flat_rate_rule)
		resolved = registry.resolve_option(
			context, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule)
		)
		self.assertEqual(resolved, flat)
		self.assertEqual(decode_option_id(resolved.option_id), (PROVIDER_ID, self.masters.flat_rate_rule))

		with self.assertRaises(MalformedShippingOptionIdError):
			registry.resolve_option(context, self.masters.flat_rate_rule)

	def test_the_context_mirrors_the_cart(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)

		self.assertEqual(context.cart_id, reference.cart_id)
		self.assertEqual(context.company, self.masters.company)
		self.assertEqual(context.currency, quotation.currency)
		self.assertEqual(
			context.company_currency,
			frappe.db.get_value("Company", self.masters.company, "default_currency"),
		)
		self.assertEqual(context.conversion_rate, 1.0)
		self.assertGreater(context.base_net_total, 0)
		self.assertIsNone(context.country)
		self.assertEqual(context.region_id, reference.region_id)
		self.assertEqual(context.sales_channel_id, reference.sales_channel_id)

	def test_the_context_carries_the_shipping_country(self) -> None:
		reference, quotation = self._cart_with_line(
			shipping_address={"country_code": "US", "address_1": "1 Main St", "city": "New York"}
		)
		self.assertEqual(
			ShippingQuoteContext.from_cart(reference, quotation).country, self.masters.shipping_country
		)

	def test_a_falsy_conversion_rate_falls_back_to_one(self) -> None:
		reference, quotation = self._cart_with_line()
		quotation.conversion_rate = 0  # in-memory: the cart flow pins rate 1
		self.assertEqual(ShippingQuoteContext.from_cart(reference, quotation).conversion_rate, 1.0)

	def test_the_context_is_frozen(self) -> None:
		reference, quotation = self._cart_with_line()
		context = ShippingQuoteContext.from_cart(reference, quotation)
		with self.assertRaises(FrozenInstanceError):
			context.company = "Other Co"

	def test_a_cart_without_identity_is_refused(self) -> None:
		reference, quotation = self._cart_with_line()
		reference.cart_id = "   "  # in-memory
		with self.assertRaises(InvalidDataError):
			ShippingQuoteContext.from_cart(reference, quotation)
