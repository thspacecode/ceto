import unittest

from ceto.types.http.store.products.manifest import (
	PRODUCT_API_SOURCE_URL,
	PRODUCT_LIST_DEFAULT_LIMIT,
	PRODUCT_LIST_DEFAULT_OFFSET,
	PRODUCT_LIST_MAX_LIMIT,
	PRODUCT_OPTION_API_SOURCE_URL,
	PRODUCT_OPTION_LIST_DEFAULT_LIMIT,
	PRODUCT_OPTION_LIST_DEFAULT_OFFSET,
	PRODUCT_OPTION_LIST_MAX_LIMIT,
	PRODUCT_OPTION_ROUTES,
	PRODUCT_OPTION_SDK_METHODS,
	PRODUCT_ROUTES,
	PRODUCT_SDK_METHODS,
	PRODUCT_SDK_PACKAGE,
	PRODUCT_SDK_VERSION,
	PRODUCT_SERVER_PACKAGE,
	PRODUCT_SERVER_VERSION,
	PRODUCT_TYPES_PACKAGE,
	PRODUCT_TYPES_VERSION,
	PRODUCT_VARIANT_API_SOURCE_URL,
	PRODUCT_VARIANT_LIST_DEFAULT_LIMIT,
	PRODUCT_VARIANT_LIST_DEFAULT_OFFSET,
	PRODUCT_VARIANT_LIST_MAX_LIMIT,
	PRODUCT_VARIANT_ROUTES,
)

PRODUCT_ROUTES_TUPLES = (*PRODUCT_ROUTES, *PRODUCT_VARIANT_ROUTES, *PRODUCT_OPTION_ROUTES)

#: The slice pins exactly five GET routes.
EXPECTED_METHOD_PATHS = {
	("GET", "/store/products"),
	("GET", "/store/products/{id}"),
	("GET", "/store/product-variants"),
	("GET", "/store/product-options"),
	("GET", "/store/product-options/{id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1``
#: (``http/product/store``), the ``sdk.store.product`` and
#: ``sdk.store.productOption`` method signatures (camelCase option
#: namespace) and the raw-HTTP fact that the pinned SDK has no product-
#: variant namespace; the trailing entry pins the query contract each route
#: validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/products"): (
		None,
		"StoreProductListResponse",
		"list",
		"StoreProductListParams",
	),
	("GET", "/store/products/{id}"): (
		None,
		"StoreProductResponse",
		"retrieve",
		"StoreProductParams",
	),
	("GET", "/store/product-variants"): (
		None,
		"StoreProductVariantListResponse",
		None,
		"StoreProductVariantListParams",
	),
	("GET", "/store/product-options"): (
		None,
		"StoreProductOptionListResponse",
		"list",
		"StoreProductOptionListParams",
	),
	("GET", "/store/product-options/{id}"): (
		None,
		"StoreProductOptionResponse",
		"retrieve",
		"StoreProductOptionParams",
	),
}


class TestProductRouteManifest(unittest.TestCase):
	def test_pins_exactly_the_five_product_routes(self):
		self.assertEqual(
			{(route.method, route.path) for route in PRODUCT_ROUTES_TUPLES}, EXPECTED_METHOD_PATHS
		)
		self.assertEqual(len(PRODUCT_ROUTES_TUPLES), 5)

	def test_pins_the_expected_contracts(self):
		for route in PRODUCT_ROUTES_TUPLES:
			contract = (route.request_type, route.response_type, route.sdk_method, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_expected_sdk_surfaces(self):
		self.assertEqual(set(PRODUCT_SDK_METHODS), {"list", "retrieve"})
		self.assertEqual(set(PRODUCT_OPTION_SDK_METHODS), {"list", "retrieve"})
		# The pinned SDK has no product-variant namespace at all: the
		# canonical variants list needs a raw HTTP client.
		self.assertIsNone(PRODUCT_VARIANT_ROUTES[0].sdk_method)

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(PRODUCT_API_SOURCE_URL, "https://docs.medusajs.com/api/store/products")
		self.assertEqual(
			PRODUCT_VARIANT_API_SOURCE_URL, "https://docs.medusajs.com/api/store/product-variants"
		)
		self.assertEqual(PRODUCT_OPTION_API_SOURCE_URL, "https://docs.medusajs.com/api/store/product-options")
		self.assertEqual(PRODUCT_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(PRODUCT_SDK_VERSION, "2.21.1")
		self.assertEqual(PRODUCT_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(PRODUCT_TYPES_VERSION, "2.21.1")
		self.assertEqual(PRODUCT_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(PRODUCT_SERVER_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		# Products and options default to 0/50 upstream, variants to 0/20.
		self.assertEqual((PRODUCT_LIST_DEFAULT_OFFSET, PRODUCT_LIST_DEFAULT_LIMIT), (0, 50))
		self.assertEqual((PRODUCT_VARIANT_LIST_DEFAULT_OFFSET, PRODUCT_VARIANT_LIST_DEFAULT_LIMIT), (0, 20))
		self.assertEqual((PRODUCT_OPTION_LIST_DEFAULT_OFFSET, PRODUCT_OPTION_LIST_DEFAULT_LIMIT), (0, 50))
		# Ceto decision: the read models cap one page, upstream does not.
		self.assertGreater(PRODUCT_LIST_MAX_LIMIT, PRODUCT_LIST_DEFAULT_LIMIT)
		self.assertGreater(PRODUCT_VARIANT_LIST_MAX_LIMIT, PRODUCT_VARIANT_LIST_DEFAULT_LIMIT)
		self.assertGreater(PRODUCT_OPTION_LIST_MAX_LIMIT, PRODUCT_OPTION_LIST_DEFAULT_LIMIT)

	def test_every_sdk_method_belongs_to_a_pinned_route(self):
		for methods, routes in (
			(PRODUCT_SDK_METHODS, PRODUCT_ROUTES),
			(PRODUCT_OPTION_SDK_METHODS, PRODUCT_OPTION_ROUTES),
		):
			with self.subTest(methods=methods):
				self.assertEqual({route.sdk_method for route in routes}, set(methods))
