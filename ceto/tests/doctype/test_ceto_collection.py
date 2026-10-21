"""Ceto Collection storage: minted ids, unique handles, metadata.

Runs real inserts on the test site inside a single rolled-back transaction:
the record is named by its public ``pcol_…`` id (never normalized), the
handle is the unique, normalized, strictly slug-shaped public URL segment,
and the optional ``external_id`` / ``metadata`` columns round-trip the
pinned contract — metadata canonicalized to a JSON object or refused.
``title`` is the only other served column and is required.
"""

import json
import uuid

import frappe

from ceto.services.catalog.collections import new_collection_id
from ceto.tests.utils import CetoTestSuite

HEX32 = uuid.uuid4().hex


class TestCetoCollection(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def make_collection(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Collection",
				"collection_id": new_collection_id(),
				"title": "Dev Collection",
				"handle": f"dev-{uuid.uuid4().hex[:12]}",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_collection_by_its_public_id(self) -> None:
		collection = self.make_collection()

		loaded = frappe.get_doc("Ceto Collection", collection.collection_id)
		self.assertEqual(loaded.name, collection.collection_id)
		self.assertTrue(loaded.collection_id.startswith("pcol_"))
		self.assertEqual(loaded.title, "Dev Collection")
		self.assertEqual(loaded.handle, loaded.handle.lower())

	def test_collection_id_format_is_strict(self) -> None:
		# The id is never normalized: a collection_id that is not exactly the
		# minted ``pcol_`` + 32 lowercase hex shape is refused outright, so a
		# padded or case-folded near-miss can never become an addressable record.
		for collection_id in (
			HEX32,  # missing the pcol_ prefix
			f"PCOL_{HEX32}",  # uppercase prefix
			f"pcol_{HEX32.upper()}",  # uppercase hex
			f"pcol_{HEX32[:31]}",  # one hex character short
			f"pcol_{HEX32}0",  # one hex character long
			f"pcol_g{HEX32[:31]}",  # a non-hex character inside
			f" pcol_{HEX32}",  # whitespace-padded
		):
			with self.subTest(collection_id=collection_id):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_collection(collection_id=collection_id)

	def test_collection_id_is_unique(self) -> None:
		collection = self.make_collection()

		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self.make_collection(collection_id=collection.collection_id)

	def test_title_is_required_and_stripped(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.make_collection(title=None)

		padded = self.make_collection(title="  Summer Drop  ")
		self.assertEqual(padded.title, "Summer Drop")

	def test_handle_is_normalized_before_the_slug_shape_is_enforced(self) -> None:
		# Presentation variants land on one stored value: whitespace is
		# stripped and case folded to lowercase, so ``Summer-2026`` stores as
		# ``summer-2026``.
		padded = self.make_collection(handle="  Summer-2026  ")
		self.assertEqual(padded.handle, "summer-2026")

	def test_handle_format_is_strict(self) -> None:
		for handle in (
			"Summer 2026",  # a space is not a slug separator
			"-leading",
			"trailing-",
			"double--hyphen",
			"under_score",
			"question?",
			"",
			"   ",
		):
			with self.subTest(handle=handle):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_collection(handle=handle)

	def test_handle_is_unique(self) -> None:
		collection = self.make_collection()

		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self.make_collection(handle=collection.handle)

		# The stored shape is the only address: a presentation variant of a
		# taken handle collides with it instead of minting a sibling record.
		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self.make_collection(handle=collection.handle.upper())

	def test_external_id_is_optional_and_stripped(self) -> None:
		collection = self.make_collection()
		self.assertIsNone(collection.external_id)

		padded = self.make_collection(external_id="  ext-1  ")
		self.assertEqual(padded.external_id, "ext-1")

		blank = self.make_collection(external_id="   ")
		self.assertIsNone(blank.external_id)

	def test_metadata_round_trips_as_a_canonical_json_object(self) -> None:
		# Equal payloads are byte-identical on disk: dict and string inputs
		# canonicalize to the same sorted, compact JSON, so the served
		# projection is reproducible.
		canonical = json.dumps({"b": 1, "a": [True, None]}, separators=(",", ":"), sort_keys=True)

		from_dict = self.make_collection(metadata={"b": 1, "a": [True, None]})
		self.assertEqual(from_dict.metadata, canonical)

		from_string = self.make_collection(metadata='{"b": 1, "a": [true, null]}')
		self.assertEqual(from_string.metadata, canonical)

		loaded = frappe.get_doc("Ceto Collection", from_string.collection_id)
		self.assertEqual(json.loads(loaded.metadata), {"b": 1, "a": [True, None]})

	def test_metadata_defaults_to_unset_and_never_to_an_empty_payload(self) -> None:
		collection = self.make_collection()
		self.assertIsNone(collection.metadata)

		for presented in ("", "   ", None):
			with self.subTest(presented=presented):
				self.assertIsNone(self.make_collection(metadata=presented).metadata)

	def test_metadata_must_be_a_json_object(self) -> None:
		for metadata in ("[1, 2]", '"text"', "3", "null", "{not json}", "{'single': 'quotes'}"):
			with self.subTest(metadata=metadata):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_collection(metadata=metadata)
