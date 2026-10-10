"""Catalog product categories: Store projections of the published Item Group tree.

``ProductCategoryDirectory`` projects the configured storefront roots and
their descendants (Recorded Decision 1) onto the pinned ``StoreProductCategory``
contract. The tests pin the publication boundary (nothing outside the roots —
the ``All Item Groups`` defaults included — is ever servable), the
deterministic ``lft`` pre-order walk (Recorded Decision 6), the derived
``pcat_…`` public id and the slugged handle, the real record timestamps
(Recorded Decision 8), the flat projection with the published
``parent_category_id`` (Recorded Decision 5), the count over the whole
published set before pagination, and the masked unknown or unpublished id.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from frappe.utils import get_datetime

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.product_categories import (
	PRODUCT_CATEGORY_LIST_MAX_LIMIT,
	ProductCategoryDirectory,
	category_handle,
	category_public_id,
)
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite

ROOT = "Storefront Root"
APPAREL = "Storefront Apparel"
T_SHIRTS = "Storefront T-Shirts"
GRAPHIC = "Storefront Graphic Tees"
HOODIES = "Storefront Hoodies"
OUTSIDE = "Storefront Outside"

#: The pre-order walk of the configured ``ROOT`` subtree, by ``lft``.
PUBLISHED_WALK = (ROOT, APPAREL, T_SHIRTS, GRAPHIC, HOODIES)


class TestProductCategoryDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(APPAREL, parent=ROOT, is_group=True)
		self.fixtures.item_group(T_SHIRTS, parent=APPAREL)
		self.fixtures.item_group(GRAPHIC, parent=T_SHIRTS)
		self.fixtures.item_group(HOODIES, parent=APPAREL)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self, *roots: str | None) -> Iterator[ProductCategoryDirectory]:
		"""Scope the storefront-roots configuration around one directory."""
		with self.set_conf(ceto_catalog={"category_roots": list(roots)}):
			yield ProductCategoryDirectory()

	def published_names(self, directory: ProductCategoryDirectory) -> list[str]:
		return [category.name for category in directory.published()]

	def test_publishes_only_the_configured_roots_and_their_descendants(self) -> None:
		with self.publish(ROOT) as directory:
			self.assertEqual(self.published_names(directory), list(PUBLISHED_WALK))

	def test_every_node_outside_the_roots_stays_invisible(self) -> None:
		with self.publish(ROOT) as directory:
			published = {category.name for category in directory.published()}

			# The unconfigured sibling, the NestedSet site root and every
			# unrelated ERPNext default or demo group are all outside the
			# boundary — none of them may ever surface, not even the root
			# the configured nodes descend from.
			for excluded in (OUTSIDE, "All Item Groups", "Dev Apparel", "Products", "Raw Material"):
				with self.subTest(excluded=excluded):
					if frappe.db.exists("Item Group", excluded):
						self.assertNotIn(excluded, published)
						with self.assertRaises(RouteNotFoundError):
							directory.get(category_public_id(excluded))

	def test_without_configuration_nothing_is_published(self) -> None:
		with self.publish(None) as directory:
			page = directory.list()

			self.assertEqual((page.product_categories, page.count, page.offset, page.limit), ([], 0, 0, 50))
			with self.assertRaises(RouteNotFoundError):
				directory.get(category_public_id(ROOT))

	def test_an_empty_or_unusable_root_configuration_publishes_nothing(self) -> None:
		for category_roots in ([], ["   "], "not-a-list"):
			with self.publish(category_roots) as directory:
				with self.subTest(category_roots=category_roots):
					self.assertEqual(directory.list().count, 0)

	def test_orders_the_page_as_a_preorder_walk_by_lft(self) -> None:
		with self.publish(ROOT) as directory:
			page = directory.list(limit=100)

		expected = frappe.get_all(
			"Item Group", filters={"name": ("in", list(PUBLISHED_WALK))}, order_by="lft", pluck="name"
		)
		self.assertEqual([category.name for category in page.product_categories], expected)
		self.assertEqual(expected, list(PUBLISHED_WALK))

	def test_projects_the_pinned_category_columns(self) -> None:
		stored = frappe.get_doc("Item Group", T_SHIRTS)
		with self.publish(ROOT) as directory:
			entry = directory.get(category_public_id(T_SHIRTS)).product_category

		self.assertEqual(entry.id, category_public_id(T_SHIRTS))
		self.assertRegex(entry.id, r"^pcat_[0-9a-f]{32}$")
		self.assertEqual(entry.name, T_SHIRTS)
		self.assertEqual(entry.handle, "storefront-t-shirts")
		# The hierarchy is preserved through the published parent only.
		self.assertEqual(entry.parent_category_id, category_public_id(APPAREL))
		self.assertEqual(entry.created_at, get_datetime(stored.creation))
		self.assertEqual(entry.updated_at, get_datetime(stored.modified))
		# The deliberately unmapped columns stay empty — never fabricated.
		self.assertIsNone(entry.rank)
		self.assertIsNone(entry.description)
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.deleted_at)
		self.assertIsNone(entry.parent_category)
		self.assertEqual(entry.category_children, [])

	def test_a_roots_parent_outside_the_boundary_has_no_published_parent_id(self) -> None:
		with self.publish(ROOT) as directory:
			entry = directory.get(category_public_id(ROOT)).product_category

		# ``ROOT`` hangs off ``All Item Groups``, which is not published.
		self.assertIsNone(entry.parent_category_id)

	def test_derived_ids_are_stable_and_collision_free(self) -> None:
		# The derivation is pure: stable across calls, distinct per node, and
		# independent of the publication state or any directory instance.
		self.assertEqual(category_public_id(ROOT), category_public_id(ROOT))
		self.assertNotEqual(category_public_id(ROOT), category_public_id(APPAREL))

	def test_handles_slug_the_item_group_name(self) -> None:
		self.assertEqual(category_handle("Dev Apparel"), "dev-apparel")
		self.assertEqual(category_handle("  Storefront 50% Off! "), "storefront-50-off")
		# A name that slugs to nothing falls back to itself, never empty.
		self.assertEqual(category_handle("///"), "///")
		self.assertEqual(category_handle(""), "")

	def test_multiple_roots_are_published_and_deduplicated(self) -> None:
		with self.publish(ROOT, OUTSIDE, ROOT, "Missing Root") as directory:
			self.assertEqual(
				self.published_names(directory),
				[ROOT, APPAREL, T_SHIRTS, GRAPHIC, HOODIES, OUTSIDE],
			)

	def test_a_nested_root_publishes_once_through_its_ancestor(self) -> None:
		with self.publish(APPAREL, ROOT) as directory:
			page = directory.list(limit=100)

		self.assertEqual([category.name for category in page.product_categories], list(PUBLISHED_WALK))
		self.assertEqual(page.count, len(PUBLISHED_WALK))
		apparel = next(category for category in page.product_categories if category.name == APPAREL)
		# The nested root's parent is itself published, so the id resolves.
		self.assertEqual(apparel.parent_category_id, category_public_id(ROOT))

	def test_pagination_slices_the_preorder_walk_and_counts_before_pagination(self) -> None:
		with self.publish(ROOT) as directory:
			page = directory.list(limit=2, offset=1)

		self.assertEqual(
			[category.name for category in page.product_categories],
			list(PUBLISHED_WALK[1:3]),
		)
		self.assertEqual((page.count, page.offset, page.limit), (len(PUBLISHED_WALK), 1, 2))

		with self.publish(ROOT) as directory:
			empty = directory.list(limit=2, offset=10)
		self.assertEqual(empty.product_categories, [])
		self.assertEqual((empty.count, empty.offset, empty.limit), (len(PUBLISHED_WALK), 10, 2))

		with self.publish(ROOT) as directory:
			zero = directory.list(limit=0)
		self.assertEqual((zero.product_categories, zero.count, zero.limit), ([], len(PUBLISHED_WALK), 0))

	def test_the_page_bound_is_the_manifest_maximum(self) -> None:
		with self.publish(ROOT) as directory:
			page = directory.list(limit=10_000)

		self.assertEqual(page.limit, PRODUCT_CATEGORY_LIST_MAX_LIMIT)

	def test_detail_matches_the_list_projection(self) -> None:
		with self.publish(ROOT) as directory:
			listed = {category.id: category for category in directory.published()}
			for name in PUBLISHED_WALK:
				with self.subTest(category=name):
					detail = directory.get(category_public_id(name)).product_category
					self.assertEqual(detail, listed[detail.id])

	def test_unknown_and_malformed_ids_mask_as_not_found(self) -> None:
		with self.publish(ROOT) as directory:
			for category_id in ("pcat_" + "0" * 32, "cat_123", "not-a-category", ""):
				with self.subTest(category_id=category_id):
					with self.assertRaises(RouteNotFoundError):
						directory.get(category_id)
