"""Pinned ``StoreProductCategory`` entity and envelope contracts."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.product_categories import (
	StoreProductCategory,
	StoreProductCategoryListResponse,
	StoreProductCategoryResponse,
)

TIMESTAMP = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def category(**overrides):
	kwargs = {
		"id": "cat_1",
		"name": "Apparel",
		"handle": "apparel",
	}
	kwargs.update(overrides)
	return StoreProductCategory(**kwargs)


class TestStoreProductCategoryEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = category()
		self.assertEqual((entry.id, entry.name, entry.handle), ("cat_1", "Apparel", "apparel"))
		# The pinned store type omits is_active/is_internal; publication is a
		# projection decision, never a served flag.
		self.assertFalse(hasattr(entry, "is_active"))
		self.assertFalse(hasattr(entry, "is_internal"))
		self.assertEqual(entry.category_children, [])

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		for column in ("id", "name", "handle"):
			kwargs = {key: value for key, value in category().model_dump().items() if key != column}
			with self.subTest(column=column):
				with self.assertRaises(ValidationError):
					StoreProductCategory(**kwargs)

	def test_unmapped_columns_stay_optional_and_default_to_none(self):
		# Item Group carries no description and no ranking source; Ceto never
		# fabricates metadata, external ids or soft-delete tombstones.
		entry = category()
		self.assertIsNone(entry.description)
		self.assertIsNone(entry.rank)
		self.assertIsNone(entry.parent_category_id)
		self.assertIsNone(entry.parent_category)
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)
		self.assertEqual(category(created_at=TIMESTAMP).created_at, TIMESTAMP)

	def test_the_tree_relations_are_the_pinned_recursive_shapes(self):
		parent = StoreProductCategory(id="cat_0", name="All", handle="all")
		child = category(parent_category=parent, parent_category_id="cat_0")
		self.assertEqual(child.parent_category.name, "All")
		kid = StoreProductCategory(id="cat_2", name="T-Shirts", handle="t-shirts")
		entry = category(category_children=[kid])
		self.assertEqual(entry.category_children[0].handle, "t-shirts")

	def test_the_children_default_is_not_shared_between_instances(self):
		first, second = category(), category()
		first.category_children.append(category(id="cat_2", name="T-Shirts", handle="t-shirts"))
		self.assertEqual(len(first.category_children), 1)
		self.assertEqual(second.category_children, [])


class TestStoreProductCategoryEnvelopes(unittest.TestCase):
	def test_detail_response_wraps_the_category(self):
		response = StoreProductCategoryResponse(product_category=category())
		self.assertEqual(response.product_category.handle, "apparel")

	def test_list_response_pins_the_paginated_envelope(self):
		response = StoreProductCategoryListResponse(
			product_categories=[category()], count=1, offset=0, limit=50
		)
		self.assertEqual(response.product_categories[0].id, "cat_1")
		self.assertEqual((response.count, response.offset, response.limit), (1, 0, 50))

	def test_list_response_carries_nothing_beyond_the_pinned_columns(self):
		# The pinned PaginatedResponse envelope is exactly these four columns.
		self.assertEqual(
			set(StoreProductCategoryListResponse.model_fields),
			{"product_categories", "count", "offset", "limit"},
		)

	def test_the_detail_wrapper_requires_its_category(self):
		with self.assertRaises(ValidationError):
			StoreProductCategoryResponse()
