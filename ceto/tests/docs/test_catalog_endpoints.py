"""Mechanical drift checks for docs/catalog/endpoints.md.

The four catalog taxonomy route manifests are drifted against their
documented route inventory (this doc) and the README route tables, and the
implemented surface is additionally drifted against the registered routes in
``ceto.tests.routing.test_router`` and the API boundary suites in
``ceto.tests.api.store``. Phase 2 slices 2B and 2C implement the served
halves — collections and product types (slice 2B, Ceto-stored) and the
category pair (slice 2C, the Item Group-tree projection) — so the doc, the
README and the implemented-routes section must agree on the six served
routes while the tag rows stay ⚪️; any change to a manifest, the doc or the
README catalog sections must land in all of them or these tests fail.
"""

import re
import unittest
from importlib import import_module
from pathlib import Path

from ceto.types.http.store.collections.manifest import COLLECTION_ROUTES
from ceto.types.http.store.product_categories.manifest import PRODUCT_CATEGORY_ROUTES
from ceto.types.http.store.product_tags.manifest import PRODUCT_TAG_ROUTES
from ceto.types.http.store.product_types.manifest import PRODUCT_TYPE_ROUTES

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "catalog" / "endpoints.md"
README = APP_ROOT / "README.md"

MANIFEST_ROUTES = (
	*COLLECTION_ROUTES,
	*PRODUCT_CATEGORY_ROUTES,
	*PRODUCT_TAG_ROUTES,
	*PRODUCT_TYPE_ROUTES,
)

IMPLEMENTED_ROUTES = (
	("GET", "/store/collections"),
	("GET", "/store/collections/{id}"),
	("GET", "/store/product-categories"),
	("GET", "/store/product-categories/{id}"),
	("GET", "/store/product-types"),
	("GET", "/store/product-types/{id}"),
)

README_SECTIONS = (
	"### Collections",
	"### Product Categories",
	"### Product Tags",
	"### Product Types",
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


def parse_readme_catalog_rows(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README catalog tables into (method, path, status) tuples."""
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


class TestCatalogEndpointsDoc(unittest.TestCase):
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
		self.assertEqual(len(self.rows), 8)
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
		self.assertIn("https://docs.medusajs.com/api/store", self.text)

	def test_doc_records_the_pinned_sdk_coverage_facts(self):
		# Verified against the published SDK sources: collections and
		# categories are SDK-covered (the category namespace is `category`),
		# product tags and product types are not covered at all.
		self.assertIn("sdk.store.collection", self.text)
		self.assertIn("sdk.store.category", self.text)
		self.assertNotIn("sdk.store.productCategory", self.text)
		self.assertIn("no product-tag and no product-type namespace", self.text)

	def test_doc_records_the_implemented_slices_status(self):
		self.assertIn("Phase 2 slice 2A pinned the contract", self.text)
		self.assertIn("Phase 2 slices 2B and 2C register the served halves", self.text)
		self.assertIn("slice 2C serves the category pair", self.text)
		# The served slice is inventoried exactly: the two tag routes stay
		# contract-only until their behavior slice lands.
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

	def test_readme_catalog_tables_match_the_manifest(self):
		rows = parse_readme_catalog_rows(README.read_text())
		self.assertEqual(len(rows), 8)
		documented = {(method, path) for method, path, _ in rows}
		self.assertEqual(documented, {(r.method, r.path) for r in MANIFEST_ROUTES})

	def test_readme_marks_exactly_the_implemented_routes(self):
		# Slices 2B and 2C serve the collections, categories and types halves;
		# the tag rows flip to ✅ only when their behavior slice registers and
		# serves them.
		rows = parse_readme_catalog_rows(README.read_text())
		implemented = {(method, path) for method, path, status in rows if "✅" in status}
		self.assertEqual(implemented, set(IMPLEMENTED_ROUTES))
		for method, path, status in rows:
			with self.subTest(route=f"{method} {path}"):
				self.assertTrue("✅" in status or "⚪" in status)


if __name__ == "__main__":
	unittest.main()
