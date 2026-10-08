"""Mechanical checks on docs/customers/field-mapping.md.

Deliberately shallow, like the carts field-mapping test: they pin that the
mapping sections, classifications and the nine recorded Phase 0 decisions
exist so later phases can rely on the document. They do not validate the
semantic content.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "customers" / "field-mapping.md"

REQUIRED_SECTIONS = (
	"Customer → Contact + Customer (+ User)",
	"StoreCustomerAddress → Address",
	"Recorded Decisions",
)

ALLOWED_CLASSIFICATIONS = {"direct", "derived", "gap", "direct/derived"}

REQUIRED_DECISION_KEYWORDS = (
	("cus_", "external-identity"),
	("contact", "customer", "user"),
	("email", "omit"),
	("metadata", "merge"),
	("address id", "address name"),
	("default", "is_primary_address", "is_shipping_address"),
	("publishable", "boundary"),
	("registration", "replay", "401"),
	("delete", "unlink", "default slot"),
)

TABLE_ROW_RE = re.compile(r"^\|[^|]+\|[^|]+\|[^|]+\|$")


class TestCustomersFieldMappingDoc(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.text = DOC.read_text()

	def test_doc_exists_and_is_not_empty(self):
		self.assertTrue(DOC.is_file())
		self.assertGreater(len(self.text), 3000)

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
		self.assertGreater(len(rows), 15)
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
			("cus_", "Customer.name"),
			("email", "Contact.email_id"),
			("company_name", "Contact.company_name"),
			("is_default_billing", "is_primary_address"),
			("is_default_shipping", "is_shipping_address"),
			("address_1", "address_line1"),
			("postal_code", "pincode"),
			("country_code", "country"),
		):
			with self.subTest(concept=concept):
				self.assertIn(concept, self.text)
				self.assertIn(target, self.text)

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
		for keywords in REQUIRED_DECISION_KEYWORDS:
			matched = any(
				all(k.lower() in (title + " " + body).lower() for k in keywords) for title, body in decisions
			)
			with self.subTest(keywords=keywords):
				self.assertTrue(matched)

	def test_no_custom_field_commitment(self):
		self.assertIn("no Custom Fields", self.text)

	def test_contract_only_commitment(self):
		self.assertIn("Phase 0 is contract-only", self.text)


if __name__ == "__main__":
	unittest.main()
