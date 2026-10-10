"""Catalog product tags: Store projections of the live Frappe tag masters.

``ProductTagDirectory`` projects the exact live ``Tag Link`` rows of
``Item`` documents onto the pinned ``StoreProductTag`` contract. The tests
pin the served boundary (a tag serves only while its master is live and one
of its links names an existing ``Item`` — orphan links, deleted-item links
and masterless links never surface), the value-ascending order (Recorded
Decision 6), the derived ``ptag_…`` public id, the absent timestamps
(Recorded Decision 8), the deduplicated served set, the count over the
whole served set before pagination, and the masked unknown id.
"""

import frappe

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.product_tags import (
	PRODUCT_TAG_LIST_MAX_LIMIT,
	ProductTagDirectory,
	tag_public_id,
)
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite


class TestProductTagDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	def served_set(self, directory: ProductTagDirectory) -> set[str]:
		return set(directory.served_values())

	def test_serves_the_exact_live_item_tag_links(self) -> None:
		first = self.fixtures.item()
		second = self.fixtures.item()
		shared = self.fixtures.item_tag(first, "Dev Shared Tag")
		unique = self.fixtures.item_tag(second, "Dev Unique Tag")

		directory = ProductTagDirectory()

		self.assertLessEqual({"Dev Shared Tag", "Dev Unique Tag"}, self.served_set(directory))
		entry = directory.get(tag_public_id(shared)).product_tag
		self.assertEqual(entry.value, shared)
		self.assertEqual(directory.get(tag_public_id(unique)).product_tag.value, unique)

	def test_a_tag_without_any_live_item_link_stays_invisible(self) -> None:
		from ceto.services.catalog.product_tags import ensure_tag_master

		ensure_tag_master("Dev Masterless Tag")
		directory = ProductTagDirectory()

		self.assertNotIn("Dev Masterless Tag", self.served_set(directory))
		with self.assertRaises(RouteNotFoundError):
			directory.get(tag_public_id("Dev Masterless Tag"))

	def test_links_to_nonexistent_items_never_surface(self) -> None:
		orphaned = self.fixtures.orphan_tag_link("Dev Orphaned Tag")
		directory = ProductTagDirectory()

		self.assertNotIn(orphaned, self.served_set(directory))
		with self.assertRaises(RouteNotFoundError):
			directory.get(tag_public_id(orphaned))

	def test_a_live_link_whose_master_disappeared_never_surfaces(self) -> None:
		# A deleted Tag master leaves its Tag Link rows behind — link drift
		# the served boundary must not project, because the served set is
		# the live masters joined to their live item links.
		item = self.fixtures.item()
		drifted = self.fixtures.item_tag(item, "Dev Drifted Tag")
		frappe.db.delete("Tag", drifted)

		directory = ProductTagDirectory()

		self.assertNotIn(drifted, self.served_set(directory))
		with self.assertRaises(RouteNotFoundError):
			directory.get(tag_public_id(drifted))

	def test_orders_by_value_ascending(self) -> None:
		# The pinned order (Recorded Decision 6) is the value ascending: the
		# alphabetically first value must lead the page, whatever its
		# creation time.
		self.fixtures.item_tag(self.fixtures.item(), "Dev Zulu Tag")
		self.fixtures.item_tag(self.fixtures.item(), "Dev Alpha Tag")

		directory = ProductTagDirectory()
		served = directory.served_values()
		page = directory.list(limit=PRODUCT_TAG_LIST_MAX_LIMIT)

		self.assertEqual(served, sorted(served))
		values = [entry.value for entry in page.product_tags]
		self.assertEqual(values, served)
		self.assertLess(values.index("Dev Alpha Tag"), values.index("Dev Zulu Tag"))

	def test_a_value_serves_once_across_every_referencing_item(self) -> None:
		for _ in range(3):
			self.fixtures.item_tag(self.fixtures.item(), "Dev Repeated Tag")

		directory = ProductTagDirectory()

		self.assertEqual(
			[value for value in directory.served_values() if value == "Dev Repeated Tag"],
			["Dev Repeated Tag"],
		)

	def test_projects_the_pinned_tag_columns(self) -> None:
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Pinned Tag")

		entry = ProductTagDirectory().get(tag_public_id(value)).product_tag

		self.assertEqual(entry.id, tag_public_id(value))
		self.assertRegex(entry.id, r"^ptag_[0-9a-f]{32}$")
		self.assertEqual(entry.value, value)
		# A tag is a projection of other records' tags: the deliberately
		# unmapped columns stay empty — never fabricated (Recorded
		# Decision 8).
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)

	def test_pages_echo_offset_and_limit_over_the_whole_served_set(self) -> None:
		self.fixtures.item_tag(self.fixtures.item(), "Dev Zulu Tag")
		self.fixtures.item_tag(self.fixtures.item(), "Dev Alpha Tag")
		self.fixtures.item_tag(self.fixtures.item(), "Dev Midway Tag")

		directory = ProductTagDirectory()
		served = directory.served_values()
		page = directory.list(limit=2, offset=1)

		self.assertEqual([entry.value for entry in page.product_tags], served[1:3])
		self.assertEqual((page.offset, page.limit, page.count), (1, 2, len(served)))
		self.assertGreaterEqual(page.count, 3)

	def test_an_empty_page_keeps_the_count(self) -> None:
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Kept Tag")

		directory = ProductTagDirectory()
		served = directory.served_values()
		page = directory.list(limit=2, offset=10_000)

		self.assertEqual(page.product_tags, [])
		self.assertEqual((page.offset, page.limit, page.count), (10_000, 2, len(served)))
		self.assertIn(value, served)

		empty = directory.list(limit=0)
		self.assertEqual(empty.product_tags, [])
		self.assertEqual(empty.count, len(served))
		self.assertEqual(empty.limit, 0)

	def test_the_page_bound_is_the_manifest_maximum(self) -> None:
		self.fixtures.item_tag(self.fixtures.item(), "Dev Bounded Tag")

		page = ProductTagDirectory().list(limit=10_000)

		self.assertEqual(page.limit, PRODUCT_TAG_LIST_MAX_LIMIT)

	def test_get_resolves_one_served_tag(self) -> None:
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Resolved Tag")

		response = ProductTagDirectory().get(tag_public_id(value))

		self.assertEqual(response.product_tag.value, value)

	def test_detail_matches_the_list_projection(self) -> None:
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Parity Tag")

		directory = ProductTagDirectory()
		listed = next(entry for entry in directory.list(limit=100).product_tags if entry.value == value)
		retrieved = directory.get(listed.id).product_tag

		self.assertEqual(retrieved, listed)

	def test_unknown_and_malformed_ids_mask_as_not_found(self) -> None:
		directory = ProductTagDirectory()

		for tag_id in ("ptag_" + "0" * 32, "not-a-tag", "ptag_none"):
			with self.subTest(tag_id=tag_id):
				with self.assertRaises(RouteNotFoundError):
					directory.get(tag_id)

		with self.assertRaises(RouteNotFoundError):
			directory.get("")
