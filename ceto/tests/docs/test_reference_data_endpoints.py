"""Mechanical drift checks for docs/reference-data/endpoints.md.

The three reference-data route manifests are drifted against their documented
route inventory (this doc) and the README route tables; the implemented
surface is additionally drifted against the router in
``ceto.tests.routing.test_router`` and the API boundary suites in
``ceto.tests.api.store``. Phase 1 slice B registers the complete surface, so
the doc, the README and the implemented-routes section must all agree on the
full five-route surface — any change to a manifest, the doc or the README
reference-data sections must land in all of them or these tests fail.
"""

import re
import unittest
from importlib import import_module
from pathlib import Path

from ceto.types.http.store.currencies.manifest import CURRENCY_ROUTES
from ceto.types.http.store.locales.manifest import LOCALE_ROUTES
from ceto.types.http.store.regions.manifest import REGION_ROUTES

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "reference-data" / "endpoints.md"
README = APP_ROOT / "README.md"

MANIFEST_ROUTES = (*REGION_ROUTES, *CURRENCY_ROUTES, *LOCALE_ROUTES)

IMPLEMENTED_ROUTES = (
	("GET", "/store/regions"),
	("GET", "/store/regions/{id}"),
	("GET", "/store/currencies"),
	("GET", "/store/currencies/{code}"),
	("GET", "/store/locales"),
)

README_SECTIONS = ("### Currencies", "### Locales", "### Regions")

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


def parse_readme_reference_rows(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README reference-data tables into (method, path, status) tuples."""
	rows = []
	for line in text.splitlines():
		if not any(line.startswith(section) for section in README_SECTIONS):
			continue
		section = line + "\n" + text.split(line, 1)[1].split("\n### ", 1)[0]
		for row in section.splitlines():
			if not row.startswith("|") or "---" in row or "Method" in row:
				continue
			cells = [cell.strip().strip("`") for cell in row.strip().strip("|").split("|")]
			rows.append((cells[0], cells[1], cells[2]))
	return rows


def parse_implemented_routes(text: str) -> list[tuple[str, str]]:
	"""Parse the implemented-routes section headings into (method, path) tuples."""
	section = text.split("## Implemented routes", 1)[1]
	return re.findall(r"^### `([A-Z]+) (\S+)`", section, flags=re.MULTILINE)


class TestReferenceDataEndpointsDoc(unittest.TestCase):
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
		self.assertIn("https://docs.medusajs.com/api/store", self.text)

	def test_doc_records_the_phase_1_slice_b_implementation_status(self):
		self.assertIn("Phase 1 slice B registers the complete surface", self.text)
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

	def test_readme_reference_tables_match_the_manifest(self):
		rows = parse_readme_reference_rows(README.read_text())
		self.assertEqual(len(rows), 5)
		documented = {(method, path) for method, path, _ in rows}
		self.assertEqual(documented, {(r.method, r.path) for r in MANIFEST_ROUTES})

	def test_readme_marks_exactly_the_implemented_routes(self):
		rows = parse_readme_reference_rows(README.read_text())
		implemented = {(method, path) for method, path, status in rows if "✅" in status}
		self.assertEqual(implemented, set(IMPLEMENTED_ROUTES))
		for method, path, status in rows:
			with self.subTest(route=f"{method} {path}"):
				self.assertTrue("✅" in status or "⚪" in status)


if __name__ == "__main__":
	unittest.main()
