"""Mechanical drift checks for docs/shipping/endpoints.md.

The shipping-option manifest is drifted against its documented route
inventory (this doc) and the README route table, and the implemented
surface is additionally drifted against the registered routes in
``ceto.tests.routing.test_router`` and the API boundary suites in
``ceto.tests.api.store``. The shipping slice registers the complete
surface, so the doc, the README and the implemented-routes section must
agree on the two served routes; the served surface also retires the carts
docs' "no listing route" caveat, so the stale carts statements are drifted
against too — any change to a manifest, the doc, the README shipping rows
or the carts docs' provider-seam statements must land in all of them or
these tests fail.
"""

import re
import unittest
from importlib import import_module
from pathlib import Path

from ceto.types.http.store.shipping_options.manifest import SHIPPING_OPTION_ROUTES

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "shipping" / "endpoints.md"
README = APP_ROOT / "README.md"
CARTS_ENDPOINTS_DOC = APP_ROOT / "docs" / "carts" / "endpoints.md"
CARTS_FIELD_MAPPING_DOC = APP_ROOT / "docs" / "carts" / "field-mapping.md"

IMPLEMENTED_ROUTES = (
	("GET", "/store/shipping-options"),
	("POST", "/store/shipping-options/{id}/calculate"),
)

README_SECTION = "### Shipping Options"

ROUTE_ROW_RE = re.compile(r"^\|\s*\d+\s*\|")


def parse_route_table(text: str) -> list[dict[str, str]]:
	"""Parse the pinned-routes table into column dicts."""
	rows = []
	for line in text.splitlines():
		if not ROUTE_ROW_RE.match(line):
			continue
		cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		if len(cells) != 8:
			raise AssertionError(f"Route row must have 8 columns: {line}")
		rows.append(
			dict(
				zip(
					("num", "method", "path", "request", "response", "query", "auth", "sdk"),
					cells,
					strict=True,
				)
			)
		)
	return rows


def parse_readme_shipping_option_rows(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README Shipping Options table into (method, path, status) tuples."""
	section = text.split(README_SECTION, 1)[1].split("\n### ", 1)[0]
	rows = []
	for line in section.splitlines():
		if not line.startswith("|"):
			continue
		columns = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		if columns[0] == "Method" or set(columns[0]) <= {"-"}:
			continue
		rows.append((columns[0], columns[1], columns[2]))
	return rows


def parse_implemented_routes(text: str) -> list[tuple[str, str]]:
	"""Parse the implemented-routes section headings into (method, path) tuples."""
	section = text.split("## Implemented routes", 1)[1]
	return re.findall(r"^### `([A-Z]+) (\S+)`", section, flags=re.MULTILINE)


class TestShippingOptionsEndpointsDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()
		cls.rows = parse_route_table(cls.text)

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 2000)

	def test_doc_covers_exactly_the_manifest_routes(self):
		documented = {(row["method"], row["path"]) for row in self.rows}
		manifest = {(route.method, route.path) for route in SHIPPING_OPTION_ROUTES}
		self.assertEqual(len(self.rows), 2)
		self.assertEqual(documented, manifest)

	def test_doc_rows_match_the_pinned_contracts(self):
		by_key = {(route.method, route.path): route for route in SHIPPING_OPTION_ROUTES}
		for row in self.rows:
			route = by_key[(row["method"], row["path"])]
			with self.subTest(route=route):
				self.assertEqual(row["request"], route.request_type or "—")
				self.assertEqual(row["response"], route.response_type)
				self.assertEqual(row["query"], route.query_type or "—")
				self.assertEqual(row["sdk"], route.sdk_method or "—")

	def test_doc_auth_column_tracks_the_manifest_auth(self):
		by_key = {(route.method, route.path): route for route in SHIPPING_OPTION_ROUTES}
		for row in self.rows:
			with self.subTest(route=(row["method"], row["path"])):
				self.assertIn("publishable-key", row["auth"])
				self.assertEqual(by_key[(row["method"], row["path"])].auth, "publishable-key")

	def test_doc_pins_the_contract_sources(self):
		self.assertIn("@medusajs/js-sdk@2.21.1", self.text)
		self.assertIn("@medusajs/types@2.21.1", self.text)
		self.assertIn("@medusajs/medusa@2.21.1", self.text)
		self.assertIn("https://docs.medusajs.com/api/store/shipping-options", self.text)

	def test_doc_records_the_pinned_sdk_coverage_facts(self):
		# Verified against the published SDK sources: both routes hang off the
		# fulfillment namespace; no shippingOption namespace exists.
		self.assertIn("sdk.store.fulfillment", self.text)
		self.assertNotIn("sdk.store.shippingOption", self.text)
		for method in ("listCartOptions", "calculate"):
			with self.subTest(sdk_method=method):
				self.assertIn(method, self.text)
		methods = {route.sdk_method for route in SHIPPING_OPTION_ROUTES}
		self.assertEqual(methods, {"listCartOptions", "calculate"})

	def test_doc_records_the_registered_slice_status(self):
		self.assertIn("the README marks both rows ✅", " ".join(self.text.split()))
		# The served slice is inventoried exactly: the whole pinned
		# shipping-option inventory is served now.
		self.assertEqual(parse_implemented_routes(self.text), list(IMPLEMENTED_ROUTES))

	def test_doc_documents_every_implemented_route_handler(self):
		section = self.text.split("## Implemented routes", 1)[1]
		headings = re.findall(r"^### `([A-Z]+) (\S+)` — `([\w.]+)`", section, flags=re.MULTILINE)
		self.assertEqual([(method, path) for method, path, _ in headings], list(IMPLEMENTED_ROUTES))
		for method, path, handler in headings:
			with self.subTest(route=f"{method} {path}"):
				module_name, function_name = handler.rsplit(".", 1)
				self.assertIn(".api.store.", f".{module_name}.")
				module = import_module(module_name)
				self.assertTrue(callable(getattr(module, function_name)))

	def test_doc_documents_the_non_paginated_list(self):
		# The pinned list route ignores the validator page (0/20) and its
		# envelope carries no pagination, so the doc records the dead
		# defaults and the manifest grows no page bound.
		self.assertIn("`offset: 0` / `limit: 20`", self.text)
		self.assertIn("no `*_LIST_MAX_LIMIT`", self.text)
		self.assertIn("not paginated upstream", self.text)

	def test_doc_documents_the_opaque_option_ids(self):
		flat = " ".join(self.text.replace("**", "").split())
		self.assertIn("so_<base64url(provider_id + ':' + option_key)>", self.text)
		self.assertIn("never the raw ERPNext `Shipping Rule` name", flat)
		self.assertIn("legacy raw `Shipping Rule` name", self.text)
		# The apply keeps accepting the legacy raw names; this surface never
		# serves them.
		self.assertIn("docs/carts/endpoints.md", self.text)

	def test_doc_documents_the_provider_hook(self):
		self.assertIn("ceto_shipping_providers", self.text)
		self.assertIn("list_options(context)", self.text)
		self.assertIn("ShippingOptionQuote", self.text)
		for guarantee in ("Determinism", "Isolation"):
			with self.subTest(guarantee=guarantee):
				self.assertIn(f"**{guarantee}**", self.text)

	def test_doc_documents_the_cart_parity_roundtrip(self):
		self.assertIn("List → calculate → add-to-cart parity", self.text)
		self.assertIn("ceto.tests.api.store.test_shipping_options_cart_roundtrip", self.text)
		self.assertIn("POST /store/carts/{id}/shipping-methods", self.text)

	def test_doc_documents_the_erpnext_mapping_and_eligibility(self):
		self.assertIn('shipping_rule_type: "Selling"', self.text)
		self.assertIn("No-address nuance", self.text)
		self.assertIn("Currency nuance", self.text)
		self.assertIn("conversion rate", self.text)

	def test_doc_documents_the_deliberate_omissions(self):
		section = self.text.split("## Deliberate omissions and deviations", 1)[1]
		for omission in (
			"No pagination",
			"No `is_return` options",
			"No `fields` selector",
			"No fulfillment-module columns",
			"No provider `data` persistence",
			"Stricter-than-upstream validation",
			"No gateway rates",
			"Read-only surface",
		):
			with self.subTest(omission=omission):
				self.assertIn(omission, section)

	def test_readme_shipping_options_table_matches_the_manifest(self):
		rows = parse_readme_shipping_option_rows(README.read_text())
		self.assertEqual(len(rows), 2)
		documented = {(method, path) for method, path, _ in rows}
		self.assertEqual(documented, {(route.method, route.path) for route in SHIPPING_OPTION_ROUTES})

	def test_readme_marks_exactly_the_implemented_routes(self):
		# The shipping slice registers and serves the whole pinned
		# shipping-option inventory, so every README row is ✅.
		rows = parse_readme_shipping_option_rows(README.read_text())
		implemented = {(method, path) for method, path, status in rows if "✅" in status}
		self.assertEqual(implemented, set(IMPLEMENTED_ROUTES))
		for method, path, status in rows:
			with self.subTest(route=f"{method} {path}"):
				self.assertTrue("✅" in status or "⚪" in status)

	def test_carts_docs_retire_the_no_listing_route_caveat(self):
		"""The served surface retires the carts docs' stale provider-seam caveat.

		Before the shipping slice served the routes, both carts docs said
		Phase 4 had no shipping-options listing route and the public option
		id was the raw Shipping Rule name; the served surface is the
		opposite, so the stale statements must stay gone and both docs must
		point at this contract.
		"""
		carts_endpoints = CARTS_ENDPOINTS_DOC.read_text()
		self.assertNotIn("has no listing route", carts_endpoints)
		self.assertIn("docs/shipping/endpoints.md", carts_endpoints)
		self.assertIn("ceto_shipping_providers", carts_endpoints)

		carts_field_mapping = CARTS_FIELD_MAPPING_DOC.read_text()
		self.assertNotIn("deliberately not built in Phase 4", carts_field_mapping)
		self.assertIn("docs/shipping/endpoints.md", carts_field_mapping)
		# The apply row keeps pinning the two id forms.
		self.assertIn("so_` ids", carts_field_mapping)
		self.assertIn("legacy raw Shipping Rule name", carts_field_mapping)


if __name__ == "__main__":
	unittest.main()
