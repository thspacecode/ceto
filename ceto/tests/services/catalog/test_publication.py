"""The single publication authority: what the Store surface may serve.

``ceto.services.catalog.publication`` decides publication once for every
consumer, so the tests pin the whole boundary: the published Item Group set
is the configured roots plus their NestedSet descendants and nothing else —
the ``All Item Groups`` defaults included; an enabled sales item inside that
set is published, and disabled items, non-sales items and variant-family
templates are never published while their variants and standalone items
are; the resolved code is the exact stored ``Item`` code; and the category
directory reads the same published set the item rule does.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe

from ceto.services.catalog.product_categories import ProductCategoryDirectory
from ceto.services.catalog.publication import (
	is_item_published,
	published_item_code,
	published_item_group_names,
)
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite

ROOT = "Publication Root"
APPAREL = "Publication Apparel"
T_SHIRTS = "Publication T-Shirts"
OUTSIDE = "Publication Outside"


class TestPublication(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(APPAREL, parent=ROOT, is_group=True)
		self.fixtures.item_group(T_SHIRTS, parent=APPAREL)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self, *roots: str | None) -> Iterator[None]:
		"""Scope the storefront-roots configuration around one assertion."""
		with self.set_conf(ceto_catalog={"category_roots": list(roots)}):
			yield

	def published_item(self, **overrides):
		return self.fixtures.item(item_group=T_SHIRTS, **overrides)

	def test_the_published_groups_are_the_roots_and_their_descendants(self) -> None:
		with self.publish(ROOT):
			self.assertEqual(published_item_group_names(), {ROOT, APPAREL, T_SHIRTS})

	def test_every_group_outside_the_roots_stays_outside(self) -> None:
		with self.publish(ROOT):
			published = published_item_group_names()

			# The unconfigured sibling, the NestedSet site root and every
			# unrelated ERPNext default group are all outside the boundary.
			for excluded in (OUTSIDE, "All Item Groups", "Dev Apparel", "Products", "Raw Material"):
				with self.subTest(excluded=excluded):
					if frappe.db.exists("Item Group", excluded):
						self.assertNotIn(excluded, published)

	def test_without_configuration_nothing_is_published(self) -> None:
		item = self.published_item()

		with self.publish(None):
			self.assertEqual(published_item_group_names(), set())
			self.assertFalse(is_item_published(item.name))
			self.assertIsNone(published_item_code(item.name))

	def test_multiple_roots_are_published_and_unknown_roots_contribute_nothing(self) -> None:
		with self.publish(ROOT, OUTSIDE, "Missing Root"):
			self.assertEqual(published_item_group_names(), {ROOT, APPAREL, T_SHIRTS, OUTSIDE})

	def test_an_enabled_sales_item_inside_the_roots_is_published(self) -> None:
		standalone = self.published_item()

		with self.publish(ROOT):
			self.assertTrue(is_item_published(standalone.name))
			self.assertEqual(published_item_code(standalone.name), standalone.name)

	def test_an_item_outside_the_roots_is_never_published(self) -> None:
		outside = self.fixtures.item(item_group=OUTSIDE)

		with self.publish(ROOT):
			self.assertFalse(is_item_published(outside.name))
			self.assertIsNone(published_item_code(outside.name))

	def test_a_disabled_item_is_never_published(self) -> None:
		item = self.published_item(disabled=1)

		with self.publish(ROOT):
			self.assertFalse(is_item_published(item.name))
			self.assertIsNone(published_item_code(item.name))

	def test_a_non_sales_item_is_never_published(self) -> None:
		item = self.published_item(is_sales_item=0)

		with self.publish(ROOT):
			self.assertFalse(is_item_published(item.name))
			self.assertIsNone(published_item_code(item.name))

	def test_a_template_is_never_published(self) -> None:
		template = self.fixtures.template_item(item_group=T_SHIRTS)

		with self.publish(ROOT):
			self.assertFalse(is_item_published(template.name))
			self.assertIsNone(published_item_code(template.name))

	def test_a_variant_publishes_when_its_template_does_not(self) -> None:
		template = self.fixtures.template_item(item_group=T_SHIRTS)
		variant = self.fixtures.variant_item(template)

		with self.publish(ROOT):
			self.assertFalse(is_item_published(template.name))
			self.assertTrue(is_item_published(variant.name))
			self.assertEqual(published_item_code(variant.name), variant.name)

	def test_the_resolved_code_is_the_exact_stored_item_code(self) -> None:
		item = self.published_item()

		with self.publish(ROOT):
			self.assertEqual(published_item_code(item.name), item.name)
			# The boolean addresses the exact stored code only: a differently
			# cased presentation is not this code and so does not count as
			# published.
			self.assertFalse(is_item_published(item.name.lower()))

	def test_an_unknown_id_publishes_nothing(self) -> None:
		with self.publish(ROOT):
			self.assertIsNone(published_item_code("DEV-MISSING-001"))
			self.assertFalse(is_item_published("DEV-MISSING-001"))

	def test_the_category_directory_reads_the_same_published_set(self) -> None:
		inside = self.published_item()
		outside = self.fixtures.item(item_group=OUTSIDE)

		with self.publish(ROOT):
			directory = ProductCategoryDirectory()
			self.assertEqual(
				[category.name for category in directory.published()],
				[ROOT, APPAREL, T_SHIRTS],
			)
			# The item boundary is the category boundary: what the directory
			# serves is exactly what the item rule publishes.
			self.assertTrue(is_item_published(inside.name))
			self.assertFalse(is_item_published(outside.name))
