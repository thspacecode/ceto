"""Mechanical checks on docs/catalog/products-field-mapping.md.

These tests are deliberately shallow: they pin that the required mapping
sections, classifications and recorded decisions exist so the products
behavior slice can rely on the document. They do not validate the semantic
content.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "catalog" / "products-field-mapping.md"

REQUIRED_SECTIONS = (
	"Recorded decisions (products slice)",
	"Product → ERPNext `Item` / Ceto catalog",
	"Product Variant → ERPNext `Item`",
	"Product Option → Ceto-owned projection",
	"Product Image → ERPNext `File` / `Item` image",
	"Auth and error semantics",
)

ALLOWED_CLASSIFICATIONS = {"direct", "derived", "gap"}

REQUIRED_DECISION_KEYWORDS = (
	("category_roots", "storefront roots"),
	("exact ERPNext `Item` codes", "never minted"),
	("derived category ids",),
	("Ceto-owned",),
	("canonical `GET /store/product-variants`",),
	("out of scope", "calculated_price"),
)

TABLE_ROW_RE = re.compile(r"^\|[^|]+\|[^|]+\|[^|]+\|$")


def mapping_rows(text: str) -> list[str]:
	return [
		line
		for line in text.splitlines()
		if TABLE_ROW_RE.match(line) and "classification" not in line.lower() and "---" not in line
	]


class TestProductsFieldMappingDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 1000)

	def test_required_sections_present(self):
		for section in REQUIRED_SECTIONS:
			with self.subTest(section=section):
				self.assertIn(f"## {section}", self.text)

	def test_every_mapping_row_uses_known_classification(self):
		rows = mapping_rows(self.text)
		self.assertGreater(len(rows), 30)
		for row in rows:
			classification = row.rsplit("|", 2)[-2].strip().lower()
			with self.subTest(row=row):
				self.assertIn(classification, ALLOWED_CLASSIFICATIONS)

	def test_all_three_classifications_are_used(self):
		used = {row.rsplit("|", 2)[-2].strip().lower() for row in mapping_rows(self.text)}
		self.assertLessEqual({"direct", "derived", "gap"}, used)

	def test_recorded_decisions_are_present(self):
		for keywords in REQUIRED_DECISION_KEYWORDS:
			with self.subTest(keywords=keywords):
				for keyword in keywords:
					self.assertIn(keyword, self.text)

	def test_doc_pins_the_contract_sources(self):
		self.assertIn("@medusajs/types@2.21.1", self.text)
		self.assertIn("@medusajs/js-sdk@2.21.1", self.text)
		self.assertIn("@medusajs/medusa@2.21.1", self.text)
		self.assertIn("docs/catalog/field-mapping.md", self.text)
		self.assertIn("products-endpoints.md", self.text)


if __name__ == "__main__":
	unittest.main()
