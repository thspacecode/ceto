"""Pinned ``StoreCurrency`` entity contract (ERPNext record projections)."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.currencies import StoreCurrency

TIMESTAMP = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def currency(**overrides):
	kwargs = {
		"code": "usd",
		"name": "US Dollar",
		"decimal_digits": 2,
		"rounding": 0.01,
		"created_at": TIMESTAMP,
		"updated_at": TIMESTAMP,
	}
	kwargs.update(overrides)
	return StoreCurrency(**kwargs)


class TestStoreCurrencyEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = currency()
		self.assertEqual(entry.code, "usd")
		self.assertEqual(entry.name, "US Dollar")
		self.assertEqual(entry.decimal_digits, 2)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		required = ("code", "name")
		for column in required:
			kwargs = {key: value for key, value in currency().model_dump().items() if key != column}
			with self.assertRaises(ValidationError):
				StoreCurrency(**kwargs)

	def test_unmappable_columns_stay_optional_and_default_to_none(self):
		# symbol_native / deleted_at have no ERPNext source and are never
		# fabricated; record timestamps are real and stay projectable.
		entry = currency(symbol=None, symbol_native=None, decimal_digits=None, rounding=None)
		self.assertIsNone(entry.symbol)
		self.assertIsNone(entry.symbol_native)
		self.assertIsNone(entry.decimal_digits)
		self.assertIsNone(entry.rounding)
		self.assertEqual(entry.created_at, TIMESTAMP)
		self.assertEqual(entry.updated_at, TIMESTAMP)
