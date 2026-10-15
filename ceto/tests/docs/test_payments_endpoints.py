"""Mechanical drift checks for docs/payments/endpoints.md.

The payment route manifest is drifted against its documented route inventory
(this doc) and the README route table; the implemented surface is
additionally drifted against the router in ``ceto.tests.routing.test_router``.
Slices 5C/5D complete the pinned surface, so the doc, the README and the
implemented-routes section must all agree on the full three-route surface —
any change to the manifest, the doc or the README payments sections must
land in all three or these tests fail.
"""

import re
import unittest
from pathlib import Path

from ceto.types.http.store.payments.manifest import PAYMENT_ROUTES

APP_ROOT = Path(__file__).resolve().parents[3]
DOC = APP_ROOT / "docs" / "payments" / "endpoints.md"
README = APP_ROOT / "README.md"

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


def parse_readme_payments(text: str) -> list[tuple[str, str, str]]:
	"""Parse the README payment tables into (method, path, status) tuples."""
	rows = []
	for section_name in ("Payment Collections", "Payment Providers"):
		section = text.split(f"### {section_name}", 1)[1].split("\n### ", 1)[0]
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


class TestPaymentsEndpointsDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()

	def test_doc_exists_and_covers_three_routes(self):
		self.assertTrue(DOC.is_file())
		rows = parse_route_table(self.text)
		self.assertEqual(len(rows), len(PAYMENT_ROUTES))

	def test_doc_rows_match_the_manifest(self):
		rows = parse_route_table(self.text)
		for row, route in zip(rows, PAYMENT_ROUTES, strict=True):
			with self.subTest(route=route.path):
				self.assertEqual(row["method"], route.method)
				self.assertEqual(row["path"], route.path)
				self.assertEqual(row["request"], route.request_type or "—")
				self.assertEqual(row["response"], route.response_type)
				self.assertEqual(row["auth"], route.auth)
				if route.sdk_method is None:
					self.assertTrue(row["sdk"].startswith("—"), row["sdk"])
				else:
					self.assertEqual(row["sdk"], route.sdk_method)

	def test_implemented_section_matches_the_manifest(self):
		implemented = parse_implemented_routes(self.text)
		self.assertEqual(implemented, [(route.method, route.path) for route in PAYMENT_ROUTES])

	def test_readme_marks_every_payment_route_implemented(self):
		readme = parse_readme_payments(README.read_text())
		self.assertEqual(
			[(method, path) for method, path, _status in readme],
			[(route.method, route.path) for route in PAYMENT_ROUTES],
		)
		for _method, _path, status in readme:
			with self.subTest(status=status):
				self.assertTrue(status.startswith("✅"))

	def test_doc_names_the_drift_guards(self):
		for guard in (
			"test_payments_manifest",
			"test_payments_endpoints",
			"test_router",
		):
			with self.subTest(guard=guard):
				self.assertIn(guard, self.text)


if __name__ == "__main__":
	unittest.main()
