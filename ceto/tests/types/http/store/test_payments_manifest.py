import unittest

from ceto.types.http.store.payments.manifest import (
	PAYMENT_API_SOURCE_URL,
	PAYMENT_PROVIDER_LIST_DEFAULT_LIMIT,
	PAYMENT_PROVIDER_LIST_DEFAULT_OFFSET,
	PAYMENT_PROVIDERS_SOURCE_URL,
	PAYMENT_ROUTES,
	PAYMENT_SDK_METHODS,
	PAYMENT_SDK_PACKAGE,
	PAYMENT_SDK_VERSION,
	PAYMENT_SERVER_PACKAGE,
	PAYMENT_SERVER_VERSION,
	PAYMENT_TYPES_PACKAGE,
	PAYMENT_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("POST", "/store/payment-collections"),
	("POST", "/store/payment-collections/{id}/payment-sessions"),
	("GET", "/store/payment-providers"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` (the package
#: ``@medusajs/js-sdk@2.21.1`` depends on) and the SDK method signatures; the
#: route set itself against the lockstep server implementation.
EXPECTED_CONTRACTS = {
	("POST", "/store/payment-collections"): (
		"StoreCreatePaymentCollection",
		"StorePaymentCollectionResponse",
	),
	("POST", "/store/payment-collections/{id}/payment-sessions"): (
		"StoreInitializePaymentSession",
		"StorePaymentCollectionResponse",
	),
	("GET", "/store/payment-providers"): (None, "StorePaymentProviderListResponse"),
}


class TestPaymentRouteManifest(unittest.TestCase):
	def test_manifest_covers_exactly_the_3_pinned_routes(self):
		method_paths = {(route.method, route.path) for route in PAYMENT_ROUTES}
		self.assertEqual(len(PAYMENT_ROUTES), 3)
		self.assertEqual(method_paths, EXPECTED_METHOD_PATHS)

	def test_routes_are_unique(self):
		method_paths = [(route.method, route.path) for route in PAYMENT_ROUTES]
		self.assertEqual(len(method_paths), len(set(method_paths)))

	def test_official_httptypes_contracts_are_pinned(self):
		for (method, path), (request_type, response_type) in EXPECTED_CONTRACTS.items():
			route = next(r for r in PAYMENT_ROUTES if (r.method, r.path) == (method, path))
			with self.subTest(route=route):
				self.assertEqual((route.request_type, route.response_type), (request_type, response_type))

	def test_session_route_uses_the_sdk_initiate_method(self):
		route = next(
			r for r in PAYMENT_ROUTES if r.path == "/store/payment-collections/{id}/payment-sessions"
		)
		self.assertEqual(route.sdk_method, "initiatePaymentSession")

	def test_collection_create_route_has_no_dedicated_sdk_method(self):
		# The pinned SDK creates the cart's collection inline from
		# initiatePaymentSession; no standalone store method exists.
		route = next(r for r in PAYMENT_ROUTES if r.path == "/store/payment-collections")
		self.assertIsNone(route.sdk_method)

	def test_providers_route_is_query_only_and_region_scoped(self):
		route = next(r for r in PAYMENT_ROUTES if r.path == "/store/payment-providers")
		self.assertEqual(route.method, "GET")
		self.assertIsNone(route.request_type)

	def test_only_the_providers_list_keeps_the_bare_publishable_key(self):
		authors = {route.path: route.auth for route in PAYMENT_ROUTES}
		self.assertEqual(
			authors,
			{
				"/store/payment-collections": "publishable-key+optional-session",
				"/store/payment-collections/{id}/payment-sessions": "publishable-key+optional-session",
				"/store/payment-providers": "publishable-key",
			},
		)

	def test_sdk_source_and_version_are_pinned(self):
		self.assertEqual(PAYMENT_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(PAYMENT_SDK_VERSION, "2.21.1")
		self.assertEqual(PAYMENT_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(PAYMENT_TYPES_VERSION, "2.21.1")
		self.assertEqual(PAYMENT_API_SOURCE_URL, "https://docs.medusajs.com/api/store/payment-collections")
		self.assertEqual(
			PAYMENT_PROVIDERS_SOURCE_URL, "https://docs.medusajs.com/api/store/payment-providers"
		)

	def test_server_implementation_source_is_pinned(self):
		self.assertEqual(PAYMENT_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(PAYMENT_SERVER_VERSION, "2.21.1")

	def test_sdk_coverage_of_pinned_methods(self):
		self.assertEqual(set(PAYMENT_SDK_METHODS), {"listPaymentProviders", "initiatePaymentSession"})

	def test_routes_without_sdk_method_are_collection_create_only(self):
		uncovered = {(route.method, route.path) for route in PAYMENT_ROUTES if route.sdk_method is None}
		self.assertEqual(uncovered, {("POST", "/store/payment-collections")})

	def test_provider_list_pagination_defaults_are_pinned(self):
		self.assertEqual(PAYMENT_PROVIDER_LIST_DEFAULT_LIMIT, 20)
		self.assertEqual(PAYMENT_PROVIDER_LIST_DEFAULT_OFFSET, 0)


if __name__ == "__main__":
	unittest.main()
