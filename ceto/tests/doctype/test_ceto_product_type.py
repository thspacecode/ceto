"""Ceto Product Type storage: minted ids, unique curated values, metadata.

Runs real inserts on the test site inside a single rolled-back transaction:
the record is named by its public ``ptyp_…`` id (never normalized), the
curated ``value`` is the unique business key — stripped, otherwise verbatim,
because a curated label is presentation whose case is never folded — and the
optional ``external_id`` / ``metadata`` columns round-trip the pinned
contract, metadata canonicalized to a JSON object or refused.
"""

import json
import uuid

import frappe

from ceto.services.catalog.product_types import new_product_type_id
from ceto.tests.utils import CetoTestSuite

HEX32 = uuid.uuid4().hex


class TestCetoProductType(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def make_type(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Product Type",
				"type_id": new_product_type_id(),
				"value": f"Dev Type {uuid.uuid4().hex[:8]}",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_type_by_its_public_id(self) -> None:
		product_type = self.make_type()

		loaded = frappe.get_doc("Ceto Product Type", product_type.type_id)
		self.assertEqual(loaded.name, product_type.type_id)
		self.assertTrue(loaded.type_id.startswith("ptyp_"))

	def test_type_id_format_is_strict(self) -> None:
		# The id is never normalized: a type_id that is not exactly the
		# minted ``ptyp_`` + 32 lowercase hex shape is refused outright.
		for type_id in (
			HEX32,  # missing the ptyp_ prefix
			f"PTYP_{HEX32}",  # uppercase prefix
			f"ptyp_{HEX32.upper()}",  # uppercase hex
			f"ptyp_{HEX32[:31]}",  # one hex character short
			f"ptyp_{HEX32}0",  # one hex character long
			f"ptyp_g{HEX32[:31]}",  # a non-hex character inside
			f" ptyp_{HEX32}",  # whitespace-padded
		):
			with self.subTest(type_id=type_id):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_type(type_id=type_id)

	def test_type_id_is_unique(self) -> None:
		product_type = self.make_type()

		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self.make_type(type_id=product_type.type_id)

	def test_value_is_required_and_stripped(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.make_type(value=None)

		padded = self.make_type(value="  Physical  ")
		self.assertEqual(padded.value, "Physical")

	def test_value_is_unique_and_verbatim(self) -> None:
		# The value is the curated label and the record's stable business
		# key: a duplicate fails closed at insert. The label is stored
		# verbatim — its curated case is never folded — and the schema's
		# unique index refuses case-variants of a taken value as well, so
		# two stored labels can never differ only by case.
		product_type = self.make_type(value="Physical")

		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self.make_type(value="Physical")

		stored = frappe.get_doc("Ceto Product Type", product_type.type_id)
		self.assertEqual(stored.value, "Physical")

		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self.make_type(value="physical")

	def test_external_id_is_optional_and_stripped(self) -> None:
		product_type = self.make_type()
		self.assertIsNone(product_type.external_id)

		padded = self.make_type(external_id="  ext-type-1  ")
		self.assertEqual(padded.external_id, "ext-type-1")

		blank = self.make_type(external_id="   ")
		self.assertIsNone(blank.external_id)

	def test_metadata_round_trips_as_a_canonical_json_object(self) -> None:
		canonical = json.dumps({"a": {"b": 2}, "z": False}, separators=(",", ":"), sort_keys=True)

		from_dict = self.make_type(metadata={"z": False, "a": {"b": 2}})
		self.assertEqual(from_dict.metadata, canonical)

		from_string = self.make_type(metadata='{"z": false, "a": {"b": 2}}')
		self.assertEqual(from_string.metadata, canonical)

		loaded = frappe.get_doc("Ceto Product Type", from_string.type_id)
		self.assertEqual(json.loads(loaded.metadata), {"a": {"b": 2}, "z": False})

	def test_metadata_defaults_to_unset_and_never_to_an_empty_payload(self) -> None:
		product_type = self.make_type()
		self.assertIsNone(product_type.metadata)

		for presented in ("", "   ", None):
			with self.subTest(presented=presented):
				self.assertIsNone(self.make_type(metadata=presented).metadata)

	def test_metadata_must_be_a_json_object(self) -> None:
		for metadata in ("[1, 2]", '"text"', "3", "null", "{not json}", "{'single': 'quotes'}"):
			with self.subTest(metadata=metadata):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_type(metadata=metadata)
