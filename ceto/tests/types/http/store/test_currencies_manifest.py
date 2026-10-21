import unittest

from ceto.types.http.store.currencies.manifest import (
	CURRENCY_API_SOURCE_URL,
	CURRENCY_LIST_DEFAULT_LIMIT,
	CURRENCY_LIST_DEFAULT_OFFSET,
	CURRENCY_LIST_MAX_LIMIT,
	CURRENCY_ROUTES,
	CURRENCY_SERVER_PACKAGE,
	CURRENCY_SERVER_VERSION,
	CURRENCY_TYPES_PACKAGE,
	CURRENCY_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {
	("GET", "/store/currencies"),
	("GET", "/store/currencies/{code}"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1`` (``http/currency/store``).
#: The pinned ``@medusajs/js-sdk@2.21.1`` ships no currency namespace at all,
#: so both routes have ``sdk_method = None`` (raw HTTP client only); the
#: trailing entry pins the query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/currencies"): (
		None,
		"StoreCurrencyListResponse",
		"StoreGetCurrencyListParams",
	),
	("GET", "/store/currencies/{code}"): (
		None,
		"StoreCurrencyResponse",
		"StoreGetCurrencyParams",
	),
}


class TestCurrencyRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual({(route.method, route.path) for route in CURRENCY_ROUTES}, EXPECTED_METHOD_PATHS)

	def test_pins_the_expected_contracts(self):
		for route in CURRENCY_ROUTES:
			contract = (route.request_type, route.response_type, route.query_type)
			self.assertEqual(contract, EXPECTED_CONTRACTS[(route.method, route.path)])
			self.assertEqual(route.auth, "publishable-key")

	def test_pins_the_routes_the_sdk_does_not_cover(self):
		# The pinned SDK has no currency namespace; every route needs a raw client.
		self.assertTrue(CURRENCY_ROUTES)
		self.assertTrue(all(route.sdk_method is None for route in CURRENCY_ROUTES))

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(CURRENCY_API_SOURCE_URL, "https://docs.medusajs.com/api/store/currencies")
		self.assertEqual(CURRENCY_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(CURRENCY_TYPES_VERSION, "2.21.1")
		self.assertEqual(CURRENCY_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(CURRENCY_SERVER_VERSION, "2.21.1")

	def test_pins_the_upstream_pagination_defaults(self):
		self.assertEqual(CURRENCY_LIST_DEFAULT_LIMIT, 50)
		self.assertEqual(CURRENCY_LIST_DEFAULT_OFFSET, 0)
		# Ceto decision: the read model caps one page, upstream does not.
		self.assertGreater(CURRENCY_LIST_MAX_LIMIT, CURRENCY_LIST_DEFAULT_LIMIT)
