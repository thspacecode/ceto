"""Pinned ``StoreCollection`` entity and envelope contracts."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.collections import (
	StoreCollection,
	StoreCollectionListResponse,
	StoreCollectionResponse,
)

TIMESTAMP = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def collection(**overrides):
	kwargs = {
		"id": "pcol_1",
		"title": "Summer 2026",
		"handle": "summer-2026",
	}
	kwargs.update(overrides)
	return StoreCollection(**kwargs)


class TestStoreCollectionEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = collection()
		self.assertEqual((entry.id, entry.title, entry.handle), ("pcol_1", "Summer 2026", "summer-2026"))
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.external_id)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		for column in ("id", "title", "handle"):
			kwargs = {key: value for key, value in collection().model_dump().items() if key != column}
			with self.subTest(column=column):
				with self.assertRaises(ValidationError):
					StoreCollection(**kwargs)

	def test_unmapped_columns_stay_optional_and_default_to_none(self):
		# Ceto never fabricates metadata, external ids or soft-delete
		# tombstones; the storage slice serves the record timestamps.
		entry = collection()
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)
		self.assertEqual(collection(created_at=TIMESTAMP, updated_at=TIMESTAMP).created_at, TIMESTAMP)


class TestStoreCollectionEnvelopes(unittest.TestCase):
	def test_detail_response_wraps_the_collection(self):
		response = StoreCollectionResponse(collection=collection())
		self.assertEqual(response.collection.handle, "summer-2026")

	def test_list_response_pins_the_paginated_envelope(self):
		response = StoreCollectionListResponse(collections=[collection()], count=1, offset=0, limit=10)
		self.assertEqual(response.collections[0].id, "pcol_1")
		self.assertEqual((response.count, response.offset, response.limit), (1, 0, 10))

	def test_list_response_carries_nothing_beyond_the_pinned_columns(self):
		# The pinned PaginatedResponse envelope is exactly these four columns.
		self.assertEqual(
			set(StoreCollectionListResponse.model_fields), {"collections", "count", "offset", "limit"}
		)

	def test_pagination_columns_cannot_be_omitted(self):
		with self.assertRaises(ValidationError):
			StoreCollectionListResponse(collections=[], count=0, offset=0)
		with self.assertRaises(ValidationError):
			StoreCollectionListResponse(collections=[], count=0, limit=10)

	def test_the_detail_wrapper_requires_its_collection(self):
		with self.assertRaises(ValidationError):
			StoreCollectionResponse()
