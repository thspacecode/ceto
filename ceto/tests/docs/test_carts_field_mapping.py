"""Mechanical checks on docs/carts/field-mapping.md.

These tests are deliberately shallow: they pin that the required mapping
sections, classifications and recorded decisions exist so later phases can
rely on the document. They do not validate the semantic content.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "carts" / "field-mapping.md"

REQUIRED_SECTIONS = (
	"Cart → Quotation",
	"Line Item → Quotation Item",
	"Address → Address",
	"Promotion → Pricing Rule + Coupon Code",
	"Shipping Method → Shipping Rule + Taxes",
	"Tax Lines → Quotation taxes and charges",
	"Completion → Sales Order",
	"Recorded Decisions",
)

ALLOWED_CLASSIFICATIONS = {"direct", "derived", "gap", "direct/derived"}

REQUIRED_DECISION_KEYWORDS = (
	("region", "sales channel"),
	("guest",),
	("frappe", "contact", "customer"),
	("cart-scoped", "temporary", "relink"),
	("publishable", "http boundary"),
	("store credit", "ledger"),
	("payment readiness",),
	("no custom fields",),
	("display_id", "order reference"),
)

TABLE_ROW_RE = re.compile(r"^\|[^|]+\|[^|]+\|[^|]+\|$")


class TestCartsFieldMappingDoc(unittest.TestCase):
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
		rows = [
			line
			for line in self.text.splitlines()
			if TABLE_ROW_RE.match(line) and "classification" not in line.lower() and "---" not in line
		]
		self.assertGreater(len(rows), 20)
		for row in rows:
			classification = row.rsplit("|", 2)[-2].strip().lower()
			with self.subTest(row=row):
				self.assertIn(classification, ALLOWED_CLASSIFICATIONS)

	def test_all_three_classifications_are_used(self):
		used = {
			row.rsplit("|", 2)[-2].strip().lower()
			for row in self.text.splitlines()
			if TABLE_ROW_RE.match(row) and "classification" not in row.lower() and "---" not in row
		}
		self.assertLessEqual({"direct", "derived", "gap"}, used)

	def test_key_concepts_are_mapped(self):
		for concept, target in (
			("customer_id", "party_name"),
			("product_variant_id", "item_code"),
			("country_code", "country"),
			("promotions", "Coupon Code"),
			("shipping_option_id", "shipping_rule"),
			("credit_lines", "Ceto Cart Credit Reservation"),
			("order", "Sales Order"),
		):
			with self.subTest(concept=concept):
				self.assertIn(concept, self.text)
				self.assertIn(target, self.text)

	def test_credit_ledger_section_documents_the_phase_5_semantics(self):
		self.assertIn("## Cart Credit (gift card / store credit)", self.text)
		# Hash-only codes and the negative Actual booking are the two decisions
		# clients and implementers must not get wrong.
		self.assertIn("SHA-256 `code_hash`", self.text)
		self.assertIn("negative `Actual` row", self.text)
		self.assertIn("total + discount_total + credit_line_total == subtotal + tax_total", self.text)

	def test_nine_decisions_are_recorded(self):
		decision_lines = re.findall(r"^\d+\. \*\*", self.text, re.MULTILINE)
		self.assertEqual(len(decision_lines), 9)

	def test_decisions_cover_required_topics(self):
		decisions = re.findall(
			r"^\d+\. \*\*(.+?)\*\*(.*?)(?=^\d+\. |\Z)",
			self.text,
			re.MULTILINE | re.DOTALL,
		)
		self.assertEqual(len(decisions), 9)
		for title, body in decisions:
			blob = (title + " " + body).lower()
			for keywords in REQUIRED_DECISION_KEYWORDS:
				if any(k.lower() in blob for k in keywords):
					break
		for keywords in REQUIRED_DECISION_KEYWORDS:
			matched = any(all(k.lower() in (t + " " + b).lower() for k in keywords) for t, b in decisions)
			with self.subTest(keywords=keywords):
				self.assertTrue(matched)

	def test_no_custom_field_commitment(self):
		self.assertIn("**No Custom Fields**", self.text)


if __name__ == "__main__":
	unittest.main()
