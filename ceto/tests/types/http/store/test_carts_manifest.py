import unittest

from ceto.types.http.store.carts.manifest import (
	CART_API_SOURCE_URL,
	CART_ROUTES,
	CART_SDK_METHODS,
	CART_SDK_PACKAGE,
	CART_SDK_VERSION,
	CART_TYPES_PACKAGE,
	CART_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/carts/{id}"),
	("POST", "/store/carts/{id}/gift-cards"),
	("POST", "/store/carts/{id}/line-items"),
	("POST", "/store/carts/{id}/promotions"),
	("POST", "/store/carts/{id}/shipping-methods"),
	("POST", "/store/carts/{id}/store-credits"),
	("POST", "/store/carts/{id}/taxes"),
	("POST", "/store/carts/{id}/customer"),
	("POST", "/store/carts/{id}/complete"),
	("POST", "/store/carts"),
	("POST", "/store/carts/{id}"),
	("POST", "/store/carts/{id}/line-items/{line_id}"),
	("DELETE", "/store/carts/{id}/gift-cards"),
	("DELETE", "/store/carts/{id}/line-items/{line_id}"),
	("DELETE", "/store/carts/{id}/promotions"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` (the package
#: ``@medusajs/js-sdk@2.21.1`` depends on) and the SDK method signatures.
EXPECTED_CONTRACTS = {
	("GET", "/store/carts/{id}"): (None, "StoreCartResponse", "retrieve"),
	("POST", "/store/carts"): ("StoreCreateCart", "StoreCartResponse", "create"),
	("POST", "/store/carts/{id}"): ("StoreUpdateCart", "StoreCartResponse", "update"),
	("POST", "/store/carts/{id}/line-items"): (
		"StoreAddCartLineItem",
		"StoreCartResponse",
		"createLineItem",
	),
	("POST", "/store/carts/{id}/line-items/{line_id}"): (
		"StoreUpdateCartLineItem",
		"StoreCartResponse",
		"updateLineItem",
	),
	("DELETE", "/store/carts/{id}/line-items/{line_id}"): (
		None,
		"StoreLineItemDeleteResponse",
		"deleteLineItem",
	),
	("POST", "/store/carts/{id}/shipping-methods"): (
		"StoreAddCartShippingMethods",
		"StoreCartResponse",
		"addShippingMethod",
	),
	("POST", "/store/carts/{id}/promotions"): (
		"StoreCartAddPromotion",
		"StoreCartResponse",
		"addPromotions",
	),
	("DELETE", "/store/carts/{id}/promotions"): (
		"StoreCartRemovePromotion",
		"StoreCartResponse",
		"removePromotions",
	),
	("POST", "/store/carts/{id}/taxes"): (
		"StoreCalculateCartTaxes",
		"StoreCartResponse",
		None,
	),
	("POST", "/store/carts/{id}/customer"): (None, "StoreCartResponse", "transferCart"),
	("POST", "/store/carts/{id}/complete"): (
		"StoreCompleteCart",
		"StoreCompleteCartResponse",
		"complete",
	),
}


class TestCartRouteManifest(unittest.TestCase):
	def test_manifest_covers_exactly_the_15_pinned_routes(self):
		method_paths = {(route.method, route.path) for route in CART_ROUTES}
		self.assertEqual(len(CART_ROUTES), 15)
		self.assertEqual(method_paths, EXPECTED_METHOD_PATHS)

	def test_routes_are_unique(self):
		method_paths = [(route.method, route.path) for route in CART_ROUTES]
		self.assertEqual(len(method_paths), len(set(method_paths)))

	def test_contract_fields_are_populated(self):
		for route in CART_ROUTES:
			with self.subTest(route=route):
				self.assertTrue(route.path.startswith("/store/carts"))
				self.assertTrue(route.response_type.startswith("Store"))
				self.assertIn(
					route.auth,
					(
						"publishable-key",
						"publishable-key+optional-session",
						"publishable-key+customer-session",
					),
				)

	def test_official_httptypes_contracts_are_pinned(self):
		for (method, path), contract in EXPECTED_CONTRACTS.items():
			route = next(r for r in CART_ROUTES if (r.method, r.path) == (method, path))
			with self.subTest(route=route):
				self.assertEqual((route.request_type, route.response_type, route.sdk_method), contract)

	def test_delete_promotions_carries_request_body(self):
		route = next(
			r for r in CART_ROUTES if (r.method, r.path) == ("DELETE", "/store/carts/{id}/promotions")
		)
		self.assertEqual(route.request_type, "StoreCartRemovePromotion")

	def test_transfer_cart_requires_customer_session(self):
		route = next(r for r in CART_ROUTES if (r.method, r.path) == ("POST", "/store/carts/{id}/customer"))
		self.assertEqual(route.auth, "publishable-key+customer-session")

	def test_sdk_source_and_version_are_pinned(self):
		self.assertEqual(CART_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(CART_SDK_VERSION, "2.21.1")
		self.assertEqual(CART_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(CART_TYPES_VERSION, "2.21.1")
		self.assertEqual(CART_API_SOURCE_URL, "https://docs.medusajs.com/api/store/carts")

	def test_sdk_coverage_of_pinned_methods(self):
		self.assertEqual(
			set(CART_SDK_METHODS),
			{
				"create",
				"retrieve",
				"update",
				"createLineItem",
				"updateLineItem",
				"deleteLineItem",
				"addShippingMethod",
				"addPromotions",
				"removePromotions",
				"complete",
				"transferCart",
			},
		)

	def test_routes_without_sdk_method_are_taxes_gift_cards_and_store_credits(self):
		uncovered = {(route.method, route.path) for route in CART_ROUTES if route.sdk_method is None}
		self.assertEqual(
			uncovered,
			{
				("POST", "/store/carts/{id}/taxes"),
				("POST", "/store/carts/{id}/gift-cards"),
				("POST", "/store/carts/{id}/store-credits"),
				("DELETE", "/store/carts/{id}/gift-cards"),
			},
		)


if __name__ == "__main__":
	unittest.main()
