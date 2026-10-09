"""Pinned ``StoreRegion`` entity contract (config-backed projections)."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.regions import StoreRegion, StoreRegionCountry

TIMESTAMP = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def region(**overrides):
	kwargs = {
		"id": "reg_us",
		"name": "United States",
		"currency_code": "usd",
	}
	kwargs.update(overrides)
	return StoreRegion(**kwargs)


class TestStoreRegionEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = region()
		self.assertEqual(entry.id, "reg_us")
		self.assertTrue(entry.automatic_taxes)
		self.assertIsNone(entry.countries)
		self.assertIsNone(entry.metadata)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		required = ("id", "name", "currency_code")
		for column in required:
			kwargs = {key: value for key, value in region().model_dump().items() if key != column}
			with self.assertRaises(ValidationError):
				StoreRegion(**kwargs)

	def test_config_backed_timestamps_stay_optional_and_default_to_none(self):
		# Ceto never fabricates timestamps for config-backed regions.
		entry = region()
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertEqual(region(created_at=TIMESTAMP).created_at, TIMESTAMP)

	def test_automatic_taxes_is_a_projected_invariant(self):
		self.assertTrue(region(automatic_taxes=True).automatic_taxes)
		self.assertFalse(region(automatic_taxes=False).automatic_taxes)

	def test_countries_mirror_the_pinned_country_columns(self):
		entry = region(
			countries=[StoreRegionCountry(id="country-us", iso_2="us", display_name="United States")]
		)
		self.assertEqual(entry.countries[0].iso_2, "us")
		self.assertIsNone(entry.countries[0].num_code)
