"""Catalog product types: read-only Store projections of the Ceto-stored records.

``ProductTypeDirectory`` projects the ``Ceto Product Type`` storage DocType
onto the pinned ``StoreProductType`` contract. The tests pin the
value-ascending order (record id breaking ties), the page echo and the count
over the whole stored set, the real record timestamps, the verbatim
``external_id`` / ``metadata`` projection, the manifest page bound, and the
masked unknown id.
"""

import frappe
from frappe.utils import get_datetime

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.product_types import PRODUCT_TYPE_LIST_MAX_LIMIT, ProductTypeDirectory
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite


class TestProductTypeDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	def stored_ids_by_value(self) -> list[str]:
		"""The pinned order, read straight off the storage: value asc, id asc."""
		rows = frappe.get_all(
			"Ceto Product Type",
			fields=("type_id", "value"),
			order_by="value asc, name asc",
		)
		return [row.type_id for row in rows]

	def test_lists_every_stored_type_with_the_pinned_projection(self) -> None:
		stored = self.fixtures.product_type(
			value="Dev Physical",
			external_id=" ext-type-1 ",
			metadata={"curated": True},
		)

		page = ProductTypeDirectory().list(limit=100)

		ids = [entry.id for entry in page.product_types]
		self.assertEqual(page.count, frappe.db.count("Ceto Product Type"))
		self.assertIn(stored.type_id, ids)
		entry = page.product_types[ids.index(stored.type_id)]
		self.assertEqual(entry.value, "Dev Physical")
		# The stored columns serve verbatim: the optional external id and
		# metadata are the record's own, and the timestamps are the real
		# record timestamps, never fabricated.
		self.assertEqual(entry.external_id, "ext-type-1")
		self.assertEqual(entry.metadata, {"curated": True})
		self.assertIsNotNone(entry.created_at)
		self.assertIsNotNone(entry.updated_at)
		self.assertEqual(entry.created_at, get_datetime(stored.creation))
		self.assertEqual(entry.updated_at, get_datetime(stored.modified))
		self.assertIsNone(entry.deleted_at)

	def test_orders_by_value_ascending_with_the_record_id_breaking_ties(self) -> None:
		# The pinned order (Recorded Decision 6) is the value ascending; two
		# types that cannot share a value still prove the tie-break through
		# the whole-table comparison against the storage order itself.
		self.fixtures.product_type(value="Dev Zeta")
		self.fixtures.product_type(value="Dev Alpha")
		self.fixtures.product_type(value="Dev Midway")

		page = ProductTypeDirectory().list(limit=100)

		ids = [entry.id for entry in page.product_types]
		self.assertEqual(ids, self.stored_ids_by_value())
		values = [entry.value for entry in page.product_types]
		self.assertEqual(values, sorted(values))

	def test_pages_echo_offset_and_limit_over_the_whole_stored_set(self) -> None:
		for _ in range(3):
			self.fixtures.product_type()

		everything = self.stored_ids_by_value()
		page = ProductTypeDirectory().list(limit=2, offset=1)

		self.assertEqual([entry.id for entry in page.product_types], everything[1:3])
		self.assertEqual((page.offset, page.limit, page.count), (1, 2, len(everything)))

	def test_an_empty_page_keeps_the_count(self) -> None:
		self.fixtures.product_type()

		page = ProductTypeDirectory().list(limit=2, offset=10_000)

		self.assertEqual(page.product_types, [])
		self.assertEqual(
			(page.offset, page.limit, page.count), (10_000, 2, frappe.db.count("Ceto Product Type"))
		)
		self.assertGreaterEqual(page.count, 1)

		empty = ProductTypeDirectory().list(limit=0)
		self.assertEqual(empty.product_types, [])
		self.assertEqual(empty.count, frappe.db.count("Ceto Product Type"))
		self.assertEqual(empty.limit, 0)

	def test_the_page_bound_is_the_manifest_maximum(self) -> None:
		self.fixtures.product_type()

		page = ProductTypeDirectory().list(limit=10_000)

		self.assertEqual(page.limit, PRODUCT_TYPE_LIST_MAX_LIMIT)

	def test_get_resolves_one_stored_type(self) -> None:
		stored = self.fixtures.product_type(metadata={"tier": "core"})

		response = ProductTypeDirectory().get(stored.type_id)

		self.assertEqual(response.product_type.id, stored.type_id)
		self.assertEqual(response.product_type.metadata, {"tier": "core"})

	def test_unknown_ids_mask_as_not_found(self) -> None:
		with self.assertRaises(RouteNotFoundError):
			ProductTypeDirectory().get("ptyp_" + "0" * 32)

		with self.assertRaises(RouteNotFoundError):
			ProductTypeDirectory().get("")

	def test_unreadable_metadata_projects_as_absent_instead_of_failing_the_read(self) -> None:
		# The controller canonicalizes every write, so a broken payload can
		# only come from outside Ceto's write path — it must never turn a
		# public read into a 500.
		stored = self.fixtures.product_type()
		frappe.db.set_value("Ceto Product Type", stored.name, "metadata", "{nope", update_modified=False)

		response = ProductTypeDirectory().get(stored.type_id)

		self.assertIsNone(response.product_type.metadata)
