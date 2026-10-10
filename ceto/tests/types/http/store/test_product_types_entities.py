"""Pinned ``StoreProductType`` entity and envelope contracts."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.product_types import (
	StoreProductType,
	StoreProductTypeListResponse,
	StoreProductTypeResponse,
)

TIMESTAMP = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def product_type(**overrides):
	kwargs = {
		"id": "ptype_1",
		"value": "Physical",
	}
	kwargs.update(overrides)
	return StoreProductType(**kwargs)


class TestStoreProductTypeEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = product_type()
		self.assertEqual((entry.id, entry.value), ("ptype_1", "Physical"))
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		for column in ("id", "value"):
			kwargs = {key: value for key, value in product_type().model_dump().items() if key != column}
			with self.subTest(column=column):
				with self.assertRaises(ValidationError):
					StoreProductType(**kwargs)

	def test_stored_record_timestamps_stay_optional_until_served(self):
		# The storage slice serves the real record timestamps; Ceto never
		# fabricates them before (Recorded Decision 8).
		entry = product_type()
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)
		self.assertEqual(product_type(created_at=TIMESTAMP, updated_at=TIMESTAMP).created_at, TIMESTAMP)


class TestStoreProductTypeEnvelopes(unittest.TestCase):
	def test_detail_response_wraps_the_type(self):
		response = StoreProductTypeResponse(product_type=product_type())
		self.assertEqual(response.product_type.value, "Physical")

	def test_list_response_pins_the_paginated_envelope(self):
		response = StoreProductTypeListResponse(product_types=[product_type()], count=1, offset=0, limit=50)
		self.assertEqual(response.product_types[0].id, "ptype_1")
		self.assertEqual((response.count, response.offset, response.limit), (1, 0, 50))

	def test_list_response_carries_nothing_beyond_the_pinned_columns(self):
		# The pinned PaginatedResponse envelope is exactly these four columns.
		self.assertEqual(
			set(StoreProductTypeListResponse.model_fields),
			{"product_types", "count", "offset", "limit"},
		)

	def test_the_detail_wrapper_requires_its_type(self):
		with self.assertRaises(ValidationError):
			StoreProductTypeResponse()
