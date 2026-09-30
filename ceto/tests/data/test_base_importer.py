"""Fast, DB-free tests for the importer foundation the bootstrap seeders share.

Only pure behavior is covered here: value comparison, owned-field application,
report bookkeeping, and identity resolution (with ``frappe.get_all`` mocked).
"""

from decimal import Decimal
from unittest.mock import patch

import frappe

from ceto.data.base_importer import BaseImporter, Report, apply_values, values_differ
from ceto.data.bootstrap_dev.setup_site import execute as setup_site_execute
from ceto.data.exceptions import AmbiguousIdentityError
from ceto.tests.utils import CetoTestSuite


class RecordingDoc:
	"""Minimal stand-in exposing the get/set surface apply_values needs."""

	def __init__(self, **fields) -> None:
		self._fields = fields
		self.written: list[str] = []

	def get(self, fieldname):
		return self._fields.get(fieldname)

	def set(self, fieldname, value):
		self.written.append(fieldname)
		self._fields[fieldname] = value


class TestValuesDiffer(CetoTestSuite):
	def test_decimals_compare_by_value_after_string_coercion(self):
		self.assertFalse(values_differ(Decimal("1.00"), Decimal("1.0")))
		self.assertFalse(values_differ("1.5", Decimal("1.5")))
		self.assertTrue(values_differ(Decimal("0"), Decimal("1.0")))
		self.assertFalse(values_differ(None, Decimal("0")))
		self.assertTrue(values_differ(None, Decimal("1.0")))

	def test_booleans_compare_by_truthiness(self):
		self.assertFalse(values_differ(1, True))
		self.assertFalse(values_differ(0, False))
		self.assertFalse(values_differ(None, False))
		self.assertTrue(values_differ(1, False))
		self.assertTrue(values_differ("", True))

	def test_none_is_treated_as_empty_string(self):
		self.assertFalse(values_differ(None, ""))
		self.assertTrue(values_differ(None, "Dev Apparel"))

	def test_null_expectation_converges_with_unset_and_empty_values(self):
		self.assertFalse(values_differ(None, None))
		self.assertFalse(values_differ("", None))
		self.assertTrue(values_differ("Dev Apparel", None))

	def test_plain_values_compare_directly(self):
		self.assertFalse(values_differ("Dev Apparel", "Dev Apparel"))
		self.assertTrue(values_differ("Dev Apparel", "Dev Hoodies"))


class TestApplyValues(CetoTestSuite):
	def test_sets_only_differing_fields_and_reports_change(self):
		doc = RecordingDoc(item_group="Dev Apparel", is_group=1, price_list_rate="10")

		changed = apply_values(doc, {"item_group": "Dev Hoodies", "is_group": False, "price_list_rate": "10"})

		self.assertTrue(changed)
		self.assertEqual(doc.written, ["item_group", "is_group"])
		self.assertEqual(doc.get("item_group"), "Dev Hoodies")
		self.assertEqual(doc.get("is_group"), False)
		self.assertEqual(doc.get("price_list_rate"), "10")

	def test_without_differences_nothing_is_written(self):
		doc = RecordingDoc(item_group="Dev Apparel", is_group=0)

		self.assertFalse(apply_values(doc, {"item_group": "Dev Apparel", "is_group": False}))

		self.assertEqual(doc.written, [])
		self.assertEqual(doc.get("item_group"), "Dev Apparel")


class TestReportBookkeeping(CetoTestSuite):
	def test_record_change_groups_names_under_doctype(self):
		importer = BaseImporter()

		importer.record_change("created", "Item Group", "Dev Apparel")
		importer.record_change("updated", "Item Group", "Dev Apparel")
		importer.record_change("created", "Item", "DEV-TSHIRT-001")

		self.assertEqual(
			importer.report["created"], {"Item Group": ["Dev Apparel"], "Item": ["DEV-TSHIRT-001"]}
		)
		self.assertEqual(importer.report["updated"], {"Item Group": ["Dev Apparel"]})
		self.assertEqual(importer.report["skipped"], {})

	def test_merge_report_accumulates_doctype_buckets_and_notes(self):
		importer = BaseImporter()
		importer.record_change("created", "Item", "DEV-TSHIRT-001")
		importer.record_note("top-level note")
		nested: Report = {
			"created": {"Item": ["DEV-HOODIE-001"]},
			"updated": {"UOM": ["Pair"]},
			"skipped": {"Item": ["DEV-TSHIRT-001"]},
			"notes": ["nested note"],
		}

		merged = importer.merge_report(nested)

		self.assertIs(merged, importer.report)
		self.assertEqual(importer.report["created"], {"Item": ["DEV-TSHIRT-001", "DEV-HOODIE-001"]})
		self.assertEqual(importer.report["updated"], {"UOM": ["Pair"]})
		self.assertEqual(importer.report["skipped"], {"Item": ["DEV-TSHIRT-001"]})
		self.assertEqual(importer.report["notes"], ["top-level note", "nested note"])


class TestIdentityResolution(CetoTestSuite):
	def test_single_match_resolves_to_its_name(self):
		importer = BaseImporter()
		filters = {"item_code": "DEV-TSHIRT-001"}

		with patch.object(frappe, "get_all", return_value=["DEV-TSHIRT-001"]) as get_all:
			self.assertEqual(importer.resolve_unique_name("Item", filters, "Dev item"), "DEV-TSHIRT-001")

		get_all.assert_called_once_with("Item", filters=filters, pluck="name")

	def test_no_match_resolves_to_none(self):
		importer = BaseImporter()

		with patch.object(frappe, "get_all", return_value=[]):
			self.assertIsNone(importer.resolve_unique_name("Item", {"item_code": "DEV-MISSING"}, "Dev item"))

	def test_multiple_matches_are_rejected_with_sorted_names(self):
		importer = BaseImporter()

		with patch.object(frappe, "get_all", return_value=["DEV-B-RATE", "DEV-A-RATE"]):
			with self.assertRaises(AmbiguousIdentityError) as raised:
				importer.resolve_unique_name(
					"Item Price", {"item_code": "DEV-TSHIRT-001"}, "Dev selling rate"
				)

		message = str(raised.exception)
		self.assertIn("Dev selling rate", message)
		self.assertIn("matched 2 Item Price records", message)
		self.assertIn("DEV-A-RATE, DEV-B-RATE", message)


class TestSettingsOverrides(CetoTestSuite):
	def test_unknown_override_is_rejected(self):
		with self.assertRaises(TypeError) as raised:
			setup_site_execute(not_a_bootstrap_setting="x")

		self.assertIn("not_a_bootstrap_setting", str(raised.exception))

	def test_derived_property_cannot_be_overridden(self):
		with self.assertRaises(TypeError) as raised:
			setup_site_execute(fiscal_year_start="2020-01-01")

		self.assertIn("fiscal_year_start", str(raised.exception))
