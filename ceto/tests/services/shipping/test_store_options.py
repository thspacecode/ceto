"""Focused tests for the store shipping-options orchestration service.

Runs against the committed ``Shipping Rule`` fixtures and real cart
Quotations: the service must compose the shared cart access, the provider
registry and the pinned entity projection without ever writing the cart,
and every unservable option must mask as the same ``404 not_found``.
"""

import frappe

from ceto.routing.exceptions import NotAllowedError, RouteNotFoundError
from ceto.services.carts.quotation import CartService
from ceto.services.shipping.ids import encode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID, ErpnextShippingRuleProvider
from ceto.services.shipping.registry import ShippingProviderRegistry
from ceto.services.shipping.service import ShippingOptionsService
from ceto.tests.data.cart_test_data import (
	SHIPPING_COUNTRY_RATE_LABEL,
	SHIPPING_DISABLED_RATE_LABEL,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreAddCartLineItem, StoreCreateCart

FOREIGN_PROVIDER_ID = "nobody"


class CountingProvider:
	"""A provider double that records every listing call."""

	id = "counting"

	def __init__(self) -> None:
		self.calls = 0

	def list_options(self, context):
		self.calls += 1
		return []


class BrokenProvider:
	"""A provider double that always crashes mid-listing."""

	id = "broken"

	def list_options(self, context):
		raise RuntimeError("provider exploded")


class TestStoreShippingOptionsService(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier module's committed cart leaves its guest-linked
		# temporary Address behind; discard it so addressless carts inherit
		# nothing (the same guard the provider suite uses).
		self.masters.discard_committed_cart_temporaries()
		self.service = ShippingOptionsService()
		self.carts = CartService()

	def _cart_with_line(self, **create_kwargs) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.carts.create(StoreCreateCart(**create_kwargs))
			self.carts.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.carts.retrieve(reference.cart_id)

	def _option_of(self, cart_id: str, rule: str):
		options = self.service.list(cart_id).shipping_options
		return next(option for option in options if option.name == rule)

	def test_list_serves_the_pinned_projection(self) -> None:
		reference, quotation = self._cart_with_line()
		response = self.service.list(reference.cart_id)

		self.assertEqual(set(response.model_dump()), {"shipping_options"})
		flat = next(option for option in response.shipping_options if option.name == SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(flat.id, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule))
		self.assertEqual(flat.price_type, "flat")
		self.assertEqual(flat.provider.model_dump(), {"id": PROVIDER_ID, "is_enabled": True})
		self.assertEqual(flat.amount, SHIPPING_FLAT_RATE_AMOUNT)
		self.assertFalse(flat.is_tax_inclusive)
		self.assertEqual(
			flat.calculated_price.model_dump(),
			{
				"calculated_amount": SHIPPING_FLAT_RATE_AMOUNT,
				"original_amount": SHIPPING_FLAT_RATE_AMOUNT,
				"currency_code": quotation.currency.lower(),
				"is_calculated_price_tax_inclusive": False,
			},
		)
		self.assertIsNone(flat.data)
		self.assertIsNone(flat.metadata)

	def test_calculate_serves_the_same_projection_as_the_list(self) -> None:
		reference, _quotation = self._cart_with_line()
		listed = self._option_of(reference.cart_id, SHIPPING_FLAT_RATE_LABEL)

		response = self.service.calculate(
			reference.cart_id, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule)
		)

		self.assertEqual(set(response.model_dump()), {"shipping_option"})
		self.assertEqual(response.shipping_option, listed)

	def test_is_return_serves_the_empty_set_without_touching_providers(self) -> None:
		reference, _quotation = self._cart_with_line()
		provider = CountingProvider()
		service = ShippingOptionsService(registry=ShippingProviderRegistry([provider]))

		response = service.list(reference.cart_id, is_return=True)

		self.assertEqual(response.shipping_options, [])
		self.assertEqual(provider.calls, 0)
		self.assertEqual(service.list(reference.cart_id, is_return=False).shipping_options, [])
		self.assertEqual(provider.calls, 1)

	def test_an_unknown_cart_is_not_found(self) -> None:
		with self.assertRaises(RouteNotFoundError):
			self.service.list("cart_missing")
		with self.assertRaises(RouteNotFoundError):
			self.service.calculate("cart_missing", encode_option_id(PROVIDER_ID, "anything"))

	def test_a_claimed_cart_masks_from_other_sessions(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_create_user():
			reference, _quotation = self.carts.create(StoreCreateCart())
			cart_id = reference.cart_id

		with self.set_user("Guest"):
			with self.assertRaises(RouteNotFoundError):
				self.service.list(cart_id)
			with self.assertRaises(RouteNotFoundError):
				self.service.calculate(cart_id, encode_option_id(PROVIDER_ID, "anything"))

	def test_the_guard_scopes_the_resolved_cart(self) -> None:
		reference, _quotation = self._cart_with_line()
		seen = []

		def guard(resolved):
			seen.append(resolved.region_id)
			raise NotAllowedError("Publishable API key cannot access this cart region")

		with self.assertRaises(NotAllowedError):
			self.service.list(reference.cart_id, guard=guard)
		with self.assertRaises(NotAllowedError):
			self.service.calculate(
				reference.cart_id, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule), guard=guard
			)
		self.assertEqual(seen, [reference.region_id, reference.region_id])

	def test_an_unknown_option_is_not_found(self) -> None:
		reference, _quotation = self._cart_with_line()
		with self.assertRaises(RouteNotFoundError):
			self.service.calculate(reference.cart_id, encode_option_id(FOREIGN_PROVIDER_ID, "key"))

	def test_a_malformed_option_id_is_not_found(self) -> None:
		reference, _quotation = self._cart_with_line()
		# The legacy raw rule name is only accepted by the cart apply
		# surface; the option surface never serves it.
		for option_id in (self.masters.flat_rate_rule, "garbage", "so_"):
			with self.subTest(option_id=option_id), self.assertRaises(RouteNotFoundError):
				self.service.calculate(reference.cart_id, option_id)

	def test_an_ineligible_option_is_not_found(self) -> None:
		reference, _quotation = self._cart_with_line(
			shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
		)
		country_id = encode_option_id(PROVIDER_ID, self.masters.country_rate_rule)
		names = [option.name for option in self.service.list(reference.cart_id).shipping_options]

		self.assertNotIn(SHIPPING_COUNTRY_RATE_LABEL, names)
		with self.assertRaises(RouteNotFoundError):
			self.service.calculate(reference.cart_id, country_id)

	def test_a_disabled_option_is_not_found(self) -> None:
		reference, _quotation = self._cart_with_line()
		disabled_id = encode_option_id(PROVIDER_ID, self.masters.disabled_rate_rule)
		names = [option.name for option in self.service.list(reference.cart_id).shipping_options]

		self.assertNotIn(SHIPPING_DISABLED_RATE_LABEL, names)
		with self.assertRaises(RouteNotFoundError):
			self.service.calculate(reference.cart_id, disabled_id)

	def test_a_broken_provider_never_fails_the_read(self) -> None:
		reference, _quotation = self._cart_with_line()
		service = ShippingOptionsService(
			registry=ShippingProviderRegistry([BrokenProvider(), ErpnextShippingRuleProvider()])
		)

		names = [option.name for option in service.list(reference.cart_id).shipping_options]

		self.assertIn(SHIPPING_FLAT_RATE_LABEL, names)

	def test_reads_never_touch_the_cart(self) -> None:
		reference, quotation = self._cart_with_line()
		before = frappe.as_json(quotation.as_dict())

		self.service.list(reference.cart_id)
		self.service.calculate(reference.cart_id, encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule))

		self.assertEqual(frappe.as_json(quotation.as_dict()), before)
