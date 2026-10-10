"""Pinned product tag query parameter contracts.

Pins the ``FindParams`` pagination of ``StoreProductTagListParams`` (the
upstream validator defaults ``offset: 0`` / ``limit: 50``), the Ceto
read-model page bound and the unknown-parameter strictness of
``@medusajs/types@2.21.1`` (``http/product-tag/store``).
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.product_tags import (
	PRODUCT_TAG_LIST_MAX_LIMIT,
	StoreProductTagListParams,
	StoreProductTagParams,
)


class TestStoreProductTagListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreProductTagListParams()
		self.assertEqual((params.offset, params.limit), (0, 50))

	def test_accepts_an_in_bounds_page(self):
		params = StoreProductTagListParams(offset=25, limit=PRODUCT_TAG_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (25, PRODUCT_TAG_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreProductTagListParams(limit=PRODUCT_TAG_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreProductTagListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreProductTagListParams(offset=-1)

	def test_rejects_the_upstream_search_and_filters(self):
		for query in (
			{"q": "summer"},
			{"id": "ptag_1"},
			{"value": "summer"},
			{"external_id": "erp-1"},
			{"created_at": {"gte": "2026-01-01"}},
			{"updated_at": {"lt": "2026-01-01"}},
			{"order": "value"},
			{"fields": "id,value"},
			{"$or": [{"value": "summer"}]},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductTagListParams(**query)


class TestStoreProductTagParams(unittest.TestCase):
	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreProductTagParams().model_dump(), {})

	def test_carries_no_field_at_all(self):
		self.assertEqual(StoreProductTagParams.model_fields, {})

	def test_rejects_every_parameter_including_the_fields_selector(self):
		for query in ({"fields": "id,value"}, {"limit": "5"}, {"q": "summer"}, {"with_deleted": "true"}):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductTagParams(**query)


if __name__ == "__main__":
	unittest.main()
