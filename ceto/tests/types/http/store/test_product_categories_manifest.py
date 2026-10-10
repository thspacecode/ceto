import unittest

from ceto.types.http.store.product_categories.manifest import (
	PRODUCT_CATEGORY_API_SOURCE_URL,
	PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT,
	PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET,
	PRODUCT_CATEGORY_LIST_MAX_LIMIT,
	PRODUCT_CATEGORY_ROUTES,
	PRODUCT_CATEGORY_SDK_METHODS,
	PRODUCT_CATEGORY_SDK_PACKAGE,
	PRODUCT_CATEGORY_SDK_VERSION,
	PRODUCT_CATEGORY_SERVER_PACKAGE,
	PRODUCT_CATEGORY_SERVER_VERSION,
	PRODUCT_CATEGORY_TYPES_PACKAGE,
	PRODUCT_CATEGORY_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/product-categories"),
	("GET", "/store/product-categories/{id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1``
#: (``http/product-category/store``) and the ``sdk.store.category`` method
#: signatures — the SDK namespace is ``category``, not ``productCategory``;
#: the trailing entry pins the query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/product-categories"): (
		None,
		"StoreProductCategoryListResponse",
		"list",
		"StoreProductCategoryListParams",
	),
	("GET", "/store/product-categories/{id}"): (
		None,
		"StoreProductCategoryResponse",
		"retrieve",
		"StoreProductCategoryParams",
	),
}


class TestProductCategoryRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual(
			{(route.method, route.path) for route in PRODUCT_CATEGORY_ROUTES}, EXPECTED_METHOD_PATHS
		)

	def test_pins_the_expected_contracts(self):
		for route in PRODUCT_CATEGORY_ROUTES:
			contract = (route.request_type, route.response_type, route.sdk_method, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_expected_sdk_surface(self):
		self.assertEqual(set(PRODUCT_CATEGORY_SDK_METHODS), {"list", "retrieve"})

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(
			PRODUCT_CATEGORY_API_SOURCE_URL, "https://docs.medusajs.com/api/store/product-categories"
		)
		self.assertEqual(PRODUCT_CATEGORY_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(PRODUCT_CATEGORY_SDK_VERSION, "2.21.1")
		self.assertEqual(PRODUCT_CATEGORY_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(PRODUCT_CATEGORY_TYPES_VERSION, "2.21.1")
		self.assertEqual(PRODUCT_CATEGORY_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(PRODUCT_CATEGORY_SERVER_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		self.assertEqual(PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT, 50)
		self.assertEqual(PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET, 0)
		# Ceto decision: the read model caps one page, upstream does not.
		self.assertGreater(PRODUCT_CATEGORY_LIST_MAX_LIMIT, PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT)

	def test_every_sdk_method_belongs_to_a_pinned_route(self):
		pinned = {route.sdk_method for route in PRODUCT_CATEGORY_ROUTES}
		self.assertEqual(pinned, set(PRODUCT_CATEGORY_SDK_METHODS))
