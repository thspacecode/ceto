import unittest

from ceto.types.http.store.locales.manifest import (
	LOCALE_API_SOURCE_URL,
	LOCALE_ROUTES,
	LOCALE_SDK_METHODS,
	LOCALE_SDK_PACKAGE,
	LOCALE_SDK_VERSION,
	LOCALE_TYPES_PACKAGE,
	LOCALE_TYPES_VERSION,
)

EXPECTED_METHOD_PATHS = {("GET", "/store/locales")}


class TestLocaleRouteManifest(unittest.TestCase):
	def test_pins_the_expected_routes(self):
		self.assertEqual({(route.method, route.path) for route in LOCALE_ROUTES}, EXPECTED_METHOD_PATHS)

	def test_pins_the_expected_contract(self):
		(route,) = LOCALE_ROUTES
		self.assertIsNone(route.request_type)
		self.assertEqual(route.response_type, "StoreLocaleListResponse")
		self.assertEqual(route.sdk_method, "list")
		self.assertEqual(route.auth, "publishable-key")
		# The pinned route accepts no query parameters (sdk.store.locale.list
		# takes headers only).
		self.assertTrue(LOCALE_ROUTES)

	def test_pins_the_expected_sdk_surface(self):
		self.assertEqual(set(LOCALE_SDK_METHODS), {"list"})

	def test_pins_the_upstream_artifacts(self):
		self.assertEqual(LOCALE_API_SOURCE_URL, "https://docs.medusajs.com/api/store/locales")
		self.assertEqual(LOCALE_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(LOCALE_SDK_VERSION, "2.21.1")
		self.assertEqual(LOCALE_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(LOCALE_TYPES_VERSION, "2.21.1")
