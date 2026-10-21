import unittest

from ceto.types.http.store.collections.manifest import (
	COLLECTION_API_SOURCE_URL,
	COLLECTION_LIST_DEFAULT_LIMIT,
	COLLECTION_LIST_DEFAULT_OFFSET,
	COLLECTION_LIST_MAX_LIMIT,
	COLLECTION_ROUTES,
	COLLECTION_SDK_METHODS,
	COLLECTION_SDK_PACKAGE,
	COLLECTION_SDK_VERSION,
	COLLECTION_SERVER_PACKAGE,
	COLLECTION_SERVER_VERSION,
	COLLECTION_TYPES_PACKAGE,
	COLLECTION_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/collections"),
	("GET", "/store/collections/{id}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1``
#: (``http/collection/store``) and the ``sdk.store.collection`` method
#: signatures; the trailing entry pins the query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/collections"): (
		None,
		"StoreCollectionListResponse",
		"list",
		"StoreCollectionListParams",
	),
	("GET", "/store/collections/{id}"): (
		None,
		"StoreCollectionResponse",
		"retrieve",
		"StoreCollectionParams",
	),
}


class TestCollectionRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual({(route.method, route.path) for route in COLLECTION_ROUTES}, EXPECTED_METHOD_PATHS)

	def test_pins_the_expected_contracts(self):
		for route in COLLECTION_ROUTES:
			contract = (route.request_type, route.response_type, route.sdk_method, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_expected_sdk_surface(self):
		self.assertEqual(set(COLLECTION_SDK_METHODS), {"list", "retrieve"})

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(COLLECTION_API_SOURCE_URL, "https://docs.medusajs.com/api/store/collections")
		self.assertEqual(COLLECTION_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(COLLECTION_SDK_VERSION, "2.21.1")
		self.assertEqual(COLLECTION_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(COLLECTION_TYPES_VERSION, "2.21.1")
		self.assertEqual(COLLECTION_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(COLLECTION_SERVER_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		self.assertEqual(COLLECTION_LIST_DEFAULT_LIMIT, 10)
		self.assertEqual(COLLECTION_LIST_DEFAULT_OFFSET, 0)
		# Ceto decision: the read model caps one page, upstream does not.
		self.assertGreater(COLLECTION_LIST_MAX_LIMIT, COLLECTION_LIST_DEFAULT_LIMIT)

	def test_every_sdk_method_belongs_to_a_pinned_route(self):
		pinned = {route.sdk_method for route in COLLECTION_ROUTES}
		self.assertEqual(pinned, set(COLLECTION_SDK_METHODS))
