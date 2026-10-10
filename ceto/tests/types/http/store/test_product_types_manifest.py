import unittest

from ceto.types.http.store.product_types.manifest import (
	PRODUCT_TYPE_API_SOURCE_URL,
	PRODUCT_TYPE_LIST_DEFAULT_LIMIT,
	PRODUCT_TYPE_LIST_DEFAULT_OFFSET,
	PRODUCT_TYPE_LIST_MAX_LIMIT,
	PRODUCT_TYPE_ROUTES,
	PRODUCT_TYPE_SERVER_PACKAGE,
	PRODUCT_TYPE_SERVER_VERSION,
	PRODUCT_TYPE_TYPES_PACKAGE,
	PRODUCT_TYPE_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/product-types"),
	("GET", "/store/product-types/{id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1``
#: (``http/product-type/store``). The pinned ``@medusajs/js-sdk@2.21.1``
#: ships no product-type namespace at all, so both routes have
#: ``sdk_method = None`` (raw HTTP client only); the trailing entry pins
#: the query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/product-types"): (
		None,
		"StoreProductTypeListResponse",
		"StoreProductTypeListParams",
	),
	("GET", "/store/product-types/{id}"): (
		None,
		"StoreProductTypeResponse",
		"StoreProductTypeParams",
	),
}


class TestProductTypeRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual({(route.method, route.path) for route in PRODUCT_TYPE_ROUTES}, EXPECTED_METHOD_PATHS)

	def test_pins_the_expected_contracts(self):
		for route in PRODUCT_TYPE_ROUTES:
			contract = (route.request_type, route.response_type, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_routes_the_sdk_does_not_cover(self):
		# The pinned SDK has no product-type namespace; every route needs a
		# raw client.
		self.assertTrue(PRODUCT_TYPE_ROUTES)
		self.assertTrue(all(route.sdk_method is None for route in PRODUCT_TYPE_ROUTES))

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(PRODUCT_TYPE_API_SOURCE_URL, "https://docs.medusajs.com/api/store/product-types")
		self.assertEqual(PRODUCT_TYPE_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(PRODUCT_TYPE_TYPES_VERSION, "2.21.1")
		self.assertEqual(PRODUCT_TYPE_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(PRODUCT_TYPE_SERVER_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		self.assertEqual(PRODUCT_TYPE_LIST_DEFAULT_LIMIT, 50)
		self.assertEqual(PRODUCT_TYPE_LIST_DEFAULT_OFFSET, 0)
		# Ceto decision: the read model caps one page, upstream does not.
		self.assertGreater(PRODUCT_TYPE_LIST_MAX_LIMIT, PRODUCT_TYPE_LIST_DEFAULT_LIMIT)
