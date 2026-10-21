"""Mechanical drift checks for docs/catalog/products-endpoints.md.

The products manifest is drifted against its documented route inventory
(this doc) and the README route tables, and the implemented surface is
additionally drifted against the registered routes in
``ceto.tests.routing.test_router`` and the API boundary suite in
``ceto.tests.api.store.test_products``. The products slice registers the
complete surface, so the doc, the README and the implemented-routes section
must agree on the five served routes — any change to a manifest, the doc or
the README product sections must land in all of them or these tests fail.
"""

import re
import unittest
from importlib import import_module
from pathlib import Path

from ceto.types.http.store.products.manifest import (
	PRODUCT_OPTION_ROUTES,
	PRODUCT_ROUTES,
	PRODUCT_VARIANT_ROUTES,
)

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "catalog" / "products-endpoints.md"
README = APP_ROOT / "README.md"

MANIFEST_ROUTES = (*PRODUCT_ROUTES, *PRODUCT_VARIANT_ROUTES, *PRODUCT_OPTION_ROUTES)

IMPLEMENTED_ROUTES = (
	("GET", "/store/products"),
	("GET", "/store/products/{id}"),
	("GET", "/store/product-variants"),
	("GET", "/store/product-options"),
	("GET", "/store/product-options/{id}"),
)

README_SECTIONS = (
	"### Products",
	"### Product Variants",
	"### Product Options",
)

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


def parse_readme_product_rows(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README product tables into (method, path, status) tuples."""
	rows = []
	lines = text.splitlines()
	for index, line in enumerate(lines):
		if line not in README_SECTIONS:
			continue
		for row in lines[index + 1 :]:
			if row.startswith("### "):
				break
			if not row.startswith("|") or "---" in row or "Method" in row:
				continue
			cells = [cell.strip().strip("`") for cell in row.strip().strip("|").split("|")]
			rows.append((cells[0], cells[1], cells[2]))
	return rows


def parse_implemented_routes(text: str) -> list[tuple[str, str]]:
	"""Parse the implemented-routes section headings into (method, path) tuples."""
	section = text.split("## Implemented routes", 1)[1]
	return re.findall(r"^### `([A-Z]+) (\S+)`", section, flags=re.MULTILINE)


class TestProductsEndpointsDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()
		cls.rows = parse_route_table(cls.text)

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 2000)

	def test_doc_covers_exactly_the_manifest_routes(self):
		documented = {(row["method"], row["path"]) for row in self.rows}
		manifest = {(route.method, route.path) for route in MANIFEST_ROUTES}
		self.assertEqual(len(self.rows), 5)
		self.assertEqual(documented, manifest)

	def test_doc_rows_match_the_pinned_contracts(self):
		by_key = {(route.method, route.path): route for route in MANIFEST_ROUTES}
		for row in self.rows:
			route = by_key[(row["method"], row["path"])]
			with self.subTest(route=route):
				self.assertEqual(row["request"], route.request_type or "—")
				self.assertEqual(row["response"], route.response_type)
				self.assertEqual(row["query"], route.query_type or "—")
				self.assertEqual(row["sdk"], route.sdk_method or "—")

	def test_doc_auth_column_tracks_the_manifest_auth(self):
		by_key = {(route.method, route.path): route for route in MANIFEST_ROUTES}
		for row in self.rows:
			with self.subTest(route=(row["method"], row["path"])):
				self.assertIn("publishable-key", row["auth"])
				self.assertEqual(by_key[(row["method"], row["path"])].auth, "publishable-key")

	def test_doc_pins_the_contract_sources(self):
		self.assertIn("@medusajs/js-sdk@2.21.1", self.text)
		self.assertIn("@medusajs/types@2.21.1", self.text)
		self.assertIn("@medusajs/medusa@2.21.1", self.text)
		self.assertIn("https://docs.medusajs.com/api/store/products", self.text)

	def test_doc_records_the_pinned_sdk_coverage_facts(self):
		# Verified against the published SDK sources: products and options
		# are SDK-covered (camelCase `productOption`), product variants are
		# not covered at all.
		self.assertIn("sdk.store.product", self.text)
		self.assertIn("sdk.store.productOption", self.text)
		self.assertNotIn("sdk.store.productVariant", self.text)
		self.assertIn("no product-variant namespace", self.text)

	def test_doc_records_the_registered_slice_status(self):
		self.assertIn("registered the complete surface", self.text)
		# The served slice is inventoried exactly: the whole pinned product
		# inventory is served now.
		self.assertEqual(parse_implemented_routes(self.text), list(IMPLEMENTED_ROUTES))
		self.assertIn("deliberately out of the pinned inventory", self.text)
		self.assertIn("/store/product-variants/{id}", self.text)

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

	def test_doc_pins_the_upstream_pagination_defaults(self):
		self.assertIn("`offset: 0` / `limit: 50`", self.text)
		self.assertIn("`offset: 0` / `limit: 20`", self.text)

	def test_readme_product_tables_match_the_manifest(self):
		rows = parse_readme_product_rows(README.read_text())
		self.assertEqual(len(rows), 5)
		documented = {(method, path) for method, path, _ in rows}
		self.assertEqual(documented, {(r.method, r.path) for r in MANIFEST_ROUTES})

	def test_readme_marks_exactly_the_implemented_routes(self):
		# The products slice registers and serves the whole pinned product
		# inventory, so every README product row is ✅.
		rows = parse_readme_product_rows(README.read_text())
		implemented = {(method, path) for method, path, status in rows if "✅" in status}
		self.assertEqual(implemented, set(IMPLEMENTED_ROUTES))
		for method, path, status in rows:
			with self.subTest(route=f"{method} {path}"):
				self.assertTrue("✅" in status or "⚪" in status)


if __name__ == "__main__":
	unittest.main()
