"""Contract tests for the pinned Store shipping-option routes manifest.

Phase 4 slice 1 pinned the contract; the behavior slice registers the
routes and serves them. The tests fail loudly on manifest drift against the
verified upstream contracts and on drift against the routes the README
advertises. They are pure Python (no Frappe imports), like the manifest
itself.
"""

import unittest
from pathlib import Path

import ceto.types.http.store.shipping_options.manifest as shipping_options_manifest
from ceto.types.http.store.shipping_options.manifest import (
	SHIPPING_OPTION_API_SOURCE_URL,
	SHIPPING_OPTION_LIST_DEFAULT_LIMIT,
	SHIPPING_OPTION_LIST_DEFAULT_OFFSET,
	SHIPPING_OPTION_ROUTES,
	SHIPPING_OPTION_SDK_METHODS,
	SHIPPING_OPTION_SDK_PACKAGE,
	SHIPPING_OPTION_SDK_VERSION,
	SHIPPING_OPTION_SERVER_PACKAGE,
	SHIPPING_OPTION_SERVER_VERSION,
	SHIPPING_OPTION_TYPES_PACKAGE,
	SHIPPING_OPTION_TYPES_VERSION,
)

#: Repo root (this file: ceto/tests/types/http/store/…, five levels down).
REPO_ROOT = Path(__file__).resolve().parents[5]
PACKAGE_ROOT = REPO_ROOT / "ceto"

#: The slice pins exactly the two upstream shipping-option routes.
EXPECTED_METHOD_PATHS = {
	("GET", "/store/shipping-options"),
	("POST", "/store/shipping-options/{id}/calculate"),
}

#: Route contracts verified against ``@medusajs/types@2.21.1``
#: (``http/shipping-option/store``), the ``sdk.store.fulfillment`` method
#: signatures of ``@medusajs/js-sdk@2.21.1`` and the lockstep server
#: middlewares of ``@medusajs/medusa@2.21.1``; the trailing entry pins the
#: query contract each route validates.
EXPECTED_CONTRACTS = {
	("GET", "/store/shipping-options"): (
		None,
		"StoreShippingOptionListResponse",
		"listCartOptions",
		"StoreGetShippingOptionList",
	),
	("POST", "/store/shipping-options/{id}/calculate"): (
		"StoreCalculateShippingOptionPrice",
		"StoreShippingOptionResponse",
		"calculate",
		"StoreShippingOptionCalculateParams",
	),
}


def readme_shipping_option_rows() -> list[tuple[str, str, str]]:
	"""Parse the Method/Route/Status rows of the README's Shipping Options table."""
	section = (REPO_ROOT / "README.md").read_text().split("### Shipping Options", 1)[1]
	section = section.split("\n### ", 1)[0]
	rows = []
	for line in section.splitlines():
		if not line.startswith("|"):
			continue
		columns = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		if columns[0] == "Method" or set(columns[0]) <= {"-"}:
			continue
		rows.append((columns[0], columns[1], columns[2]))
	return rows


class TestShippingOptionRouteManifest(unittest.TestCase):
	def test_manifest_covers_exactly_the_2_pinned_routes(self):
		method_paths = {(route.method, route.path) for route in SHIPPING_OPTION_ROUTES}
		self.assertEqual(len(SHIPPING_OPTION_ROUTES), 2)
		self.assertEqual(method_paths, EXPECTED_METHOD_PATHS)

	def test_routes_are_unique(self):
		method_paths = [(route.method, route.path) for route in SHIPPING_OPTION_ROUTES]
		self.assertEqual(len(method_paths), len(set(method_paths)))

	def test_contract_fields_are_populated(self):
		for route in SHIPPING_OPTION_ROUTES:
			with self.subTest(route=route):
				self.assertTrue(route.path.startswith("/store/shipping-options"))
				self.assertTrue(route.response_type.startswith("StoreShippingOption"))
				self.assertEqual(route.auth, "publishable-key")

	def test_official_httptypes_contracts_are_pinned(self):
		for (method, path), contract in EXPECTED_CONTRACTS.items():
			route = next(r for r in SHIPPING_OPTION_ROUTES if (r.method, r.path) == (method, path))
			with self.subTest(route=route):
				self.assertEqual((route.request_type, route.response_type, route.sdk_method), contract[:3])
				self.assertEqual(route.query_type, contract[3])

	def test_sdk_covers_every_pinned_route(self):
		"""The pinned SDK exposes both routes under ``sdk.store.fulfillment``."""
		self.assertEqual(
			{route.sdk_method for route in SHIPPING_OPTION_ROUTES},
			set(SHIPPING_OPTION_SDK_METHODS),
		)

	def test_the_list_is_not_paginated_upstream(self):
		"""The pinned route ignores the validator page (0/20) and the pinned
		list response carries no pagination — the defaults are dead upstream
		parameters, so no ``*_LIST_MAX_LIMIT`` page bound may exist."""
		self.assertEqual((SHIPPING_OPTION_LIST_DEFAULT_OFFSET, SHIPPING_OPTION_LIST_DEFAULT_LIMIT), (0, 20))
		self.assertFalse(hasattr(shipping_options_manifest, "SHIPPING_OPTION_LIST_MAX_LIMIT"))

	def test_sdk_source_and_version_are_pinned(self):
		self.assertEqual(SHIPPING_OPTION_SDK_PACKAGE, "@medusajs/js-sdk")
		self.assertEqual(SHIPPING_OPTION_SDK_VERSION, "2.21.1")
		self.assertEqual(SHIPPING_OPTION_TYPES_PACKAGE, "@medusajs/types")
		self.assertEqual(SHIPPING_OPTION_TYPES_VERSION, "2.21.1")
		self.assertEqual(SHIPPING_OPTION_SERVER_PACKAGE, "@medusajs/medusa")
		self.assertEqual(SHIPPING_OPTION_SERVER_VERSION, "2.21.1")
		self.assertEqual(
			SHIPPING_OPTION_API_SOURCE_URL, "https://docs.medusajs.com/api/store/shipping-options"
		)

	def test_readme_shipping_options_table_matches_the_manifest(self):
		"""The advertised surface is the pinned surface — README drift fails."""
		advertised = {(method, path) for method, path, _ in readme_shipping_option_rows()}
		self.assertEqual(len(advertised), 2)
		self.assertEqual(advertised, {(route.method, route.path) for route in SHIPPING_OPTION_ROUTES})

	def test_the_docs_slice_marks_the_served_routes(self):
		"""The behavior slice serves the routes and the docs slice marks them.

		The adapter module exists, ``routes.py`` wires it, and the README
		rows are ✅ — flipped exactly when the served surface was
		documented, so a status row can never drift from a served route.
		"""
		self.assertTrue((PACKAGE_ROOT / "api" / "store" / "shipping_options.py").is_file())
		self.assertIn(
			"import ceto.api.store.shipping_options", (PACKAGE_ROOT / "api" / "routes.py").read_text()
		)
		statuses = {(method, path): status for method, path, status in readme_shipping_option_rows()}
		self.assertEqual(len(statuses), 2)
		for (method, path), status in statuses.items():
			with self.subTest(route=(method, path)):
				self.assertIn("✅", status)


if __name__ == "__main__":
	unittest.main()
