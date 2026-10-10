"""Pinned product category query parameter contracts.

Pins the ``FindParams`` pagination of ``StoreProductCategoryListParams``
(the upstream validator defaults ``offset: 0`` / ``limit: 50``), the Ceto
read-model page bound and the unknown-parameter strictness of
``@medusajs/types@2.21.1`` (``http/product-category/store``) — including
the refused tree expansion flags.
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.product_categories import (
	PRODUCT_CATEGORY_LIST_MAX_LIMIT,
	StoreProductCategoryListParams,
	StoreProductCategoryParams,
)


class TestStoreProductCategoryListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreProductCategoryListParams()
		self.assertEqual((params.offset, params.limit), (0, 50))

	def test_accepts_an_in_bounds_page(self):
		params = StoreProductCategoryListParams(offset=50, limit=PRODUCT_CATEGORY_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (50, PRODUCT_CATEGORY_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreProductCategoryListParams(limit=PRODUCT_CATEGORY_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreProductCategoryListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreProductCategoryListParams(offset=-1)

	def test_rejects_the_upstream_search_and_filters(self):
		for query in (
			{"q": "apparel"},
			{"id": "cat_1"},
			{"name": "Apparel"},
			{"description": "Shirts and hoodies"},
			{"handle": "apparel"},
			{"parent_category_id": "cat_0"},
			{"external_id": "erp-1"},
			{"is_active": "true"},
			{"is_internal": "true"},
			{"created_at": {"gte": "2026-01-01"}},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductCategoryListParams(**query)

	def test_rejects_the_tree_expansion_flags(self):
		# Recorded Decision 5: the projection is flat until the tree
		# population decision lands, so both flags are unknown keys.
		for query in (
			{"include_descendants_tree": "true"},
			{"include_ancestors_tree": "true"},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductCategoryListParams(**query)

	def test_rejects_sort_fields_and_combinators(self):
		for query in (
			{"order": "name"},
			{"fields": "id,handle"},
			{"$and": [{"handle": "apparel"}]},
			{"$or": [{"name": "Apparel"}]},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductCategoryListParams(**query)


class TestStoreProductCategoryParams(unittest.TestCase):
	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreProductCategoryParams().model_dump(), {})

	def test_carries_no_field_at_all(self):
		self.assertEqual(StoreProductCategoryParams.model_fields, {})

	def test_rejects_every_parameter_including_the_tree_flags(self):
		for query in (
			{"fields": "id,handle"},
			{"limit": "5"},
			{"q": "apparel"},
			{"include_descendants_tree": "true"},
			{"include_ancestors_tree": "true"},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductCategoryParams(**query)


if __name__ == "__main__":
	unittest.main()
