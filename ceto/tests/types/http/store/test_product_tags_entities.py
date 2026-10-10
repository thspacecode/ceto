"""Pinned ``StoreProductTag`` entity and envelope contracts."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.product_tags import (
	StoreProductTag,
	StoreProductTagListResponse,
	StoreProductTagResponse,
)

TIMESTAMP = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def tag(**overrides):
	kwargs = {
		"id": "ptag_1",
		"value": "summer",
	}
	kwargs.update(overrides)
	return StoreProductTag(**kwargs)


class TestStoreProductTagEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = tag()
		self.assertEqual((entry.id, entry.value), ("ptag_1", "summer"))
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		for column in ("id", "value"):
			kwargs = {key: value for key, value in tag().model_dump().items() if key != column}
			with self.subTest(column=column):
				with self.assertRaises(ValidationError):
					StoreProductTag(**kwargs)

	def test_tag_timestamps_stay_optional_and_default_to_none(self):
		# A tag is a projection of other records' tags — Ceto never
		# fabricates a timestamp for it (Recorded Decision 8).
		entry = tag()
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)
		self.assertEqual(tag(created_at=TIMESTAMP).created_at, TIMESTAMP)


class TestStoreProductTagEnvelopes(unittest.TestCase):
	def test_detail_response_wraps_the_tag(self):
		response = StoreProductTagResponse(product_tag=tag())
		self.assertEqual(response.product_tag.value, "summer")

	def test_list_response_pins_the_paginated_envelope(self):
		response = StoreProductTagListResponse(product_tags=[tag()], count=1, offset=0, limit=50)
		self.assertEqual(response.product_tags[0].id, "ptag_1")
		self.assertEqual((response.count, response.offset, response.limit), (1, 0, 50))

	def test_list_response_carries_nothing_beyond_the_pinned_columns(self):
		# The pinned PaginatedResponse envelope is exactly these four columns.
		self.assertEqual(
			set(StoreProductTagListResponse.model_fields),
			{"product_tags", "count", "offset", "limit"},
		)

	def test_the_detail_wrapper_requires_its_tag(self):
		with self.assertRaises(ValidationError):
			StoreProductTagResponse()
