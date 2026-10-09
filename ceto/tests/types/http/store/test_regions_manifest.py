import unittest

from ceto.types.http.store.regions.manifest import (
	REGION_API_SOURCE_URL,
	REGION_LIST_DEFAULT_LIMIT,
	REGION_LIST_DEFAULT_OFFSET,
	REGION_LIST_MAX_LIMIT,
	REGION_ROUTES,
	REGION_SDK_METHODS,
	REGION_SDK_PACKAGE,
	REGION_SDK_VERSION,
	REGION_TYPES_PACKAGE,
	REGION_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/regions"),
	("GET", "/store/regions/{id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` (``http/region/store``)
#: and the ``sdk.store.region`` method signatures; the trailing entry pins the
#: query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/regions"): (
		None,
		"StoreRegionListResponse",
		"list",
		"StoreRegionFilters",
	),
	("GET", "/store/regions/{id}"): (
		None,
		"StoreRegionResponse",
		"retrieve",
		"StoreGetRegionParams",
	),
}


class TestRegionRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual({(route.method, route.path) for route in REGION_ROUTES}, EXPECTED_METHOD_PATHS)

	def test_pins_the_expected_contracts(self):
		for route in REGION_ROUTES:
			contract = (route.request_type, route.response_type, route.sdk_method, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_expected_sdk_surface(self):
		self.assertEqual(set(REGION_SDK_METHODS), {"list", "retrieve"})

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(REGION_API_SOURCE_URL, "https://docs.medusajs.com/api/store/regions")
		self.assertEqual(REGION_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(REGION_SDK_VERSION, "2.21.1")
		self.assertEqual(REGION_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(REGION_TYPES_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		self.assertEqual(REGION_LIST_DEFAULT_LIMIT, 20)
		self.assertEqual(REGION_LIST_DEFAULT_OFFSET, 0)
		# Ceto decision: the read model caps one page, upstream does not.
		self.assertGreater(REGION_LIST_MAX_LIMIT, REGION_LIST_DEFAULT_LIMIT)

	def test_every_sdk_method_belongs_to_a_pinned_route(self):
		pinned = {route.sdk_method for route in REGION_ROUTES}
		self.assertEqual(pinned, set(REGION_SDK_METHODS))
