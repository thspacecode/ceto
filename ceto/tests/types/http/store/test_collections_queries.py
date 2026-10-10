"""Pinned collection query parameter contracts.

Pins the ``FindParams`` pagination of ``StoreCollectionListParams`` (the
upstream validator defaults ``offset: 0`` / ``limit: 10``), the Ceto
read-model page bound and the unknown-parameter strictness of
``@medusajs/types@2.21.1`` (``http/collection/store``).
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.collections import (
	COLLECTION_LIST_MAX_LIMIT,
	StoreCollectionListParams,
	StoreCollectionParams,
)


class TestStoreCollectionListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreCollectionListParams()
		self.assertEqual((params.offset, params.limit), (0, 10))

	def test_accepts_an_in_bounds_page(self):
		params = StoreCollectionListParams(offset=10, limit=COLLECTION_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (10, COLLECTION_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreCollectionListParams(limit=COLLECTION_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreCollectionListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreCollectionListParams(offset=-1)

	def test_rejects_the_upstream_search_and_filters(self):
		# The pinned list params carry far more surfaces (q, id, title,
		# handle, external_id, operator maps); Ceto serves none of them.
		for query in (
			{"q": "summer"},
			{"id": "pcol_1"},
			{"title": "Summer"},
			{"handle": "summer-2026"},
			{"external_id": "erp-1"},
			{"created_at": {"gte": "2026-01-01"}},
			{"updated_at": {"lt": "2026-01-01"}},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreCollectionListParams(**query)

	def test_rejects_sort_fields_and_combinators(self):
		for query in (
			{"order": "-created_at"},
			{"fields": "id,handle"},
			{"$and": [{"handle": "summer-2026"}]},
			{"$or": [{"title": "Summer"}]},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreCollectionListParams(**query)


class TestStoreCollectionParams(unittest.TestCase):
	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreCollectionParams().model_dump(), {})

	def test_carries_no_field_at_all(self):
		self.assertEqual(StoreCollectionParams.model_fields, {})

	def test_rejects_every_parameter_including_the_fields_selector(self):
		for query in ({"fields": "id,handle"}, {"limit": "5"}, {"q": "summer"}, {"with_deleted": "true"}):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreCollectionParams(**query)


if __name__ == "__main__":
	unittest.main()
