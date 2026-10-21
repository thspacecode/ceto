"""Catalog collections: read-only Store projections of the Ceto-stored records.

``CollectionDirectory`` projects the ``Ceto Collection`` storage DocType
onto the pinned ``StoreCollection`` contract. The tests pin the deterministic
creation-descending order (record id breaking ties), the page echo and the
count over the whole stored set, the real record timestamps, the verbatim
``external_id`` / ``metadata`` projection, the manifest page bound, and the
masked unknown id.
"""

import frappe
from frappe.utils import get_datetime

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.collections import COLLECTION_LIST_MAX_LIMIT, CollectionDirectory
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite


class TestCollectionDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	def stored_ids_in_order(self) -> list[str]:
		return frappe.get_all(
			"Ceto Collection",
			fields=("collection_id",),
			order_by="creation desc, name desc",
			pluck="collection_id",
		)

	def test_lists_every_stored_collection_with_the_pinned_projection(self) -> None:
		stored = self.fixtures.collection(
			title="Dev Summer Drop",
			external_id=" ext-1 ",
			metadata={"season": "summer"},
		)

		page = CollectionDirectory().list(limit=100)

		self.assertEqual(page.count, frappe.db.count("Ceto Collection"))
		ids = [entry.id for entry in page.collections]
		self.assertIn(stored.collection_id, ids)
		entry = page.collections[ids.index(stored.collection_id)]
		self.assertEqual(entry.title, "Dev Summer Drop")
		self.assertTrue(entry.handle.startswith("dev-"))
		# The stored columns serve verbatim: the optional external id and
		# metadata are the record's own, and the timestamps are the real
		# record timestamps, never fabricated.
		self.assertEqual(entry.external_id, "ext-1")
		self.assertEqual(entry.metadata, {"season": "summer"})
		self.assertIsNotNone(entry.created_at)
		self.assertIsNotNone(entry.updated_at)
		self.assertEqual(entry.created_at, get_datetime(stored.creation))
		self.assertEqual(entry.updated_at, get_datetime(stored.modified))
		self.assertIsNone(entry.deleted_at)

	def test_orders_by_creation_descending_with_the_record_id_breaking_ties(self) -> None:
		# The upstream pinned default sort is -created_at; the newest record
		# must lead the page. Two records sharing a creation instant order by
		# the minted record id, so the page never depends on insert timing.
		first = self.fixtures.collection()
		second = self.fixtures.collection()
		frappe.db.set_value("Ceto Collection", second.name, "creation", first.creation, update_modified=False)

		page = CollectionDirectory().list(limit=100)

		leader, trailer = (second, first) if second.name > first.name else (first, second)
		ids = [entry.id for entry in page.collections]
		self.assertLess(ids.index(leader.collection_id), ids.index(trailer.collection_id))
		self.assertEqual(ids, self.stored_ids_in_order())

	def test_pages_echo_offset_and_limit_over_the_whole_stored_set(self) -> None:
		for _ in range(3):
			self.fixtures.collection()

		everything = self.stored_ids_in_order()
		page = CollectionDirectory().list(limit=2, offset=1)

		self.assertEqual([entry.id for entry in page.collections], everything[1:3])
		self.assertEqual((page.offset, page.limit, page.count), (1, 2, len(everything)))

	def test_an_empty_page_keeps_the_count(self) -> None:
		self.fixtures.collection()

		page = CollectionDirectory().list(limit=2, offset=10)

		self.assertEqual(page.collections, [])
		self.assertEqual((page.offset, page.limit, page.count), (10, 2, frappe.db.count("Ceto Collection")))
		self.assertGreaterEqual(page.count, 1)

		empty = CollectionDirectory().list(limit=0)
		self.assertEqual(empty.collections, [])
		self.assertEqual(empty.count, frappe.db.count("Ceto Collection"))
		self.assertEqual(empty.limit, 0)

	def test_the_page_bound_is_the_manifest_maximum(self) -> None:
		self.fixtures.collection()

		page = CollectionDirectory().list(limit=10_000)

		self.assertEqual(page.limit, COLLECTION_LIST_MAX_LIMIT)

	def test_get_resolves_one_stored_collection(self) -> None:
		stored = self.fixtures.collection(handle="dev-winter", metadata={"a": 1})

		response = CollectionDirectory().get(stored.collection_id)

		self.assertEqual(response.collection.id, stored.collection_id)
		self.assertEqual(response.collection.handle, "dev-winter")
		self.assertEqual(response.collection.metadata, {"a": 1})

	def test_unknown_ids_mask_as_not_found(self) -> None:
		with self.assertRaises(RouteNotFoundError):
			CollectionDirectory().get("pcol_" + "0" * 32)

		with self.assertRaises(RouteNotFoundError):
			CollectionDirectory().get("")

	def test_unreadable_metadata_projects_as_absent_instead_of_failing_the_read(self) -> None:
		# The controller canonicalizes every write, so a broken payload can
		# only come from outside Ceto's write path — it must never turn a
		# public read into a 500.
		stored = self.fixtures.collection()
		frappe.db.set_value(
			"Ceto Collection", stored.name, "metadata", "not json at all", update_modified=False
		)

		response = CollectionDirectory().get(stored.collection_id)

		self.assertIsNone(response.collection.metadata)
