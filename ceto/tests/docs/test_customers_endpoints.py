"""Mechanical drift checks for docs/customers/endpoints.md.

The customer route manifest is drifted against its documented route inventory
(this doc) and the README route table; the implemented surface is additionally
drifted against the router in ``ceto.tests.routing.test_router``. Phase 1
implements routes 1-2, so the doc, the README and the implemented-routes
section must all agree on exactly that subset — any change to the manifest,
the doc or the README customers section must land in all three or these tests
fail.
"""

import re
import unittest
from pathlib import Path

from ceto.types.http.store.customers.manifest import CUSTOMER_ROUTES

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "customers" / "endpoints.md"
README = APP_ROOT / "README.md"

IMPLEMENTED_ROUTES = (("POST", "/store/customers"), ("GET", "/store/customers/me"))

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

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


def parse_readme_customers(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README Customers table into (method, path, status) tuples."""
	section = text.split("### Customers", 1)[1].split("### ", 1)[0]
	rows = []
	for line in section.splitlines():
		if not line.startswith("|") or "---" in line or "Method" in line:
			continue
		cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
		rows.append((cells[0], cells[1], cells[2]))
	return rows


def parse_implemented_routes(text: str) -> list[tuple[str, str]]:
	"""Parse the implemented-routes section headings into (method, path) tuples."""
	section = text.split("## Implemented routes", 1)[1]
	return re.findall(r"^### `([A-Z]+) (\S+)`", section, flags=re.MULTILINE)


class TestCustomersEndpointsDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()
		cls.rows = parse_route_table(cls.text)

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 2000)

	def test_doc_covers_exactly_the_manifest_routes(self):
		documented = {(row["method"], row["path"]) for row in self.rows}
		manifest = {(route.method, route.path) for route in CUSTOMER_ROUTES}
		self.assertEqual(len(self.rows), 8)
		self.assertEqual(documented, manifest)

	def test_doc_rows_match_the_pinned_contracts(self):
		by_key = {(route.method, route.path): route for route in CUSTOMER_ROUTES}
		for row in self.rows:
			route = by_key[(row["method"], row["path"])]
			with self.subTest(route=route):
				self.assertEqual(row["request"], route.request_type or "—")
				self.assertEqual(row["response"], route.response_type)
				self.assertEqual(row["query"], route.query_type or "—")
				self.assertEqual(row["sdk"], route.sdk_method)

	def test_doc_auth_column_tracks_the_manifest_auth(self):
		by_key = {(route.method, route.path): route for route in CUSTOMER_ROUTES}
		for row in self.rows:
			auth = by_key[(row["method"], row["path"])].auth
			with self.subTest(route=(row["method"], row["path"])):
				self.assertIn("pk", row["auth"])
				if auth == "publishable-key+registration-token":
					self.assertIn("registration token", row["auth"])
				else:
					self.assertIn("customer session", row["auth"])

	def test_doc_pins_the_contract_sources(self):
		self.assertIn("@medusajs/js-sdk@2.21.1", self.text)
		self.assertIn("@medusajs/types@2.21.1", self.text)
		self.assertIn("https://docs.medusajs.com/api/store/customers", self.text)

	def test_doc_records_the_phase_1_implementation_status(self):
		self.assertIn("Phase 1 registers the first two routes", self.text)
		self.assertIn("routes 3-8 stay contract-only", self.text)
		self.assertEqual(parse_implemented_routes(self.text), list(IMPLEMENTED_ROUTES))

	def test_readme_customers_table_matches_the_manifest(self):
		readme = README.read_text()
		rows = parse_readme_customers(readme)
		self.assertEqual(len(rows), 8)
		documented = {(method, path) for method, path, _ in rows}
		self.assertEqual(documented, {(r.method, r.path) for r in CUSTOMER_ROUTES})

	def test_readme_marks_exactly_the_implemented_routes(self):
		rows = parse_readme_customers(README.read_text())
		implemented = {(method, path) for method, path, status in rows if "✅" in status}
		self.assertEqual(implemented, set(IMPLEMENTED_ROUTES))
		for method, path, status in rows:
			with self.subTest(route=f"{method} {path}"):
				self.assertTrue("✅" in status or "⚪" in status)


if __name__ == "__main__":
	unittest.main()
