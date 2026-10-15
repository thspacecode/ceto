"""Mechanical checks on docs/payments/field-mapping.md.

These tests are deliberately shallow: they pin that the required mapping
sections, classifications and recorded decisions exist so later payment
phases can rely on the document. They do not validate the semantic content.
"""

import re
import unittest
from pathlib import Path

DOC = Path(__file__).resolve().parents[3] / "docs" / "payments" / "field-mapping.md"

REQUIRED_SECTIONS = (
	"Pinned Contracts",
	"Payment Collection → Ceto Payment Collection",
	"Payment Session → Ceto Payment Session",
	"Payment Provider → Ceto provider registry → paygi",
	"Payment Policy → `ceto_cart.payment_policy`",
	"Recorded Decisions",
)

ALLOWED_CLASSIFICATIONS = {"direct", "derived", "gap", "direct/derived"}

REQUIRED_CONCEPT_TARGETS = (
	("pay_col_", "payment_collection_id"),
	("payses_", "payment_session_id"),
	("payment_collection", "Ceto Payment Collection"),
	("provider_id", "pp_beam_beam"),
	("payment_policy", "enforced"),
	("is_current", "one current session per collection"),
	("StorePaymentProvider", "@medusajs/types@2.21.1"),
)

TABLE_ROW_RE = re.compile(r"^\|[^|]+\|[^|]+\|[^|]+\|$")


class TestPaymentsFieldMappingDoc(unittest.TestCase):
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

	def test_mapping_rows_use_known_classifications(self):
		rows = [
			line
			for line in self.text.splitlines()
			if TABLE_ROW_RE.match(line) and "classification" not in line.lower() and "---" not in line
		]
		self.assertGreater(len(rows), 10)
		for row in rows:
			classification = row.rsplit("|", 2)[-2].strip().lower()
			with self.subTest(row=row):
				self.assertIn(classification, ALLOWED_CLASSIFICATIONS)

	def test_key_concepts_are_mapped(self):
		for concept, target in REQUIRED_CONCEPT_TARGETS:
			with self.subTest(concept=concept):
				self.assertIn(concept, self.text)
				self.assertIn(target, self.text)

	def test_pinned_route_table_covers_the_three_routes(self):
		for route in (
			"POST /store/payment-collections",
			"POST /store/payment-collections/{id}/payment-sessions",
			"GET /store/payment-providers",
		):
			with self.subTest(route=route):
				self.assertIn(f"`{route}`", self.text)

	def test_fourteen_decisions_are_recorded(self):
		decision_lines = re.findall(r"^\d+\. \*\*", self.text, re.MULTILINE)
		self.assertEqual(len(decision_lines), 14)

	def test_decisions_cover_the_load_bearing_topics(self):
		decisions = re.findall(
			r"^\d+\. \*\*(.+?)\*\*(.*?)(?=^\d+\. |\Z)",
			self.text,
			re.MULTILINE | re.DOTALL,
		)
		self.assertEqual(len(decisions), 14)
		for keywords in (
			("paygi", "unchanged"),
			("pp_beam_beam", "pp_stripe_stripe"),
			("defensive",),
			("fail", "closed"),
			("idempotent",),
			("stale",),
			("one collection per cart",),
			("three-route", "served"),
			("minor units",),
			("zero", "session"),
			("narrow", "privileged"),
			("absence", "500"),
			("exactly-once", "hook"),
			("proven money",),
		):
			matched = any(all(k.lower() in (t + " " + b).lower() for k in keywords) for t, b in decisions)
			with self.subTest(keywords=keywords):
				self.assertTrue(matched)

	def test_no_custom_field_commitment(self):
		self.assertIn("**not** by Custom Fields on core ERPNext", self.text)


if __name__ == "__main__":
	unittest.main()
