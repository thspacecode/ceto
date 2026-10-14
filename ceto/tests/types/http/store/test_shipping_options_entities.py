"""Pinned shipping-option entity and envelope contracts."""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.products import StoreCalculatedPrice
from ceto.types.http.store.shipping_options import (
	StoreCartShippingOption,
	StoreShippingOptionListResponse,
	StoreShippingOptionResponse,
)


def option(**overrides):
	kwargs = {
		"id": "Dev Flat Rate",
		"name": "Dev Flat Rate",
		"price_type": "flat",
	}
	kwargs.update(overrides)
	return StoreCartShippingOption(**kwargs)


class TestStoreCartShippingOptionEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = option()
		self.assertEqual((entry.id, entry.name, entry.price_type), ("Dev Flat Rate", "Dev Flat Rate", "flat"))

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-optional columns and the
		# rule master always carries them (name, label, calculate_based_on).
		for column in ("id", "name", "price_type"):
			kwargs = {key: value for key, value in option().model_dump().items() if key != column}
			with self.subTest(column=column), self.assertRaises(ValidationError):
				StoreCartShippingOption(**kwargs)

	def test_price_type_is_the_pinned_union(self):
		self.assertEqual(option(price_type="calculated").price_type, "calculated")
		with self.assertRaises(ValidationError):
			option(price_type="dynamic")

	def test_the_rate_defaults_to_the_honest_empty_value(self):
		# The rate resolves against the cart; an unresolvable context serves
		# the itemless baseline 0 with no calculated_price, never a made-up
		# amount (the cart shipping-method convention).
		entry = option()
		self.assertEqual(entry.amount, 0)
		self.assertIsNone(entry.calculated_price)

	def test_calculated_price_reuses_the_pinned_products_entity(self):
		entry = option(
			amount=50,
			calculated_price=StoreCalculatedPrice(calculated_amount=50, currency_code="th"),
		)
		self.assertEqual(entry.amount, 50)
		self.assertEqual(entry.calculated_price.calculated_amount, 50)
		self.assertEqual(entry.calculated_price.currency_code, "th")

	def test_the_fulfillment_module_columns_are_dropped_not_stubbed(self):
		# No ERPNext source exists for the fulfillment-module surfaces, so
		# they are absent from the model entirely (products precedent):
		# never optional Nones pretending to be a projection.
		self.assertEqual(
			set(StoreCartShippingOption.model_fields),
			{"id", "name", "price_type", "amount", "calculated_price"},
		)
		for column in (
			"service_zone_id",
			"shipping_profile_id",
			"provider_id",
			"type",
			"provider",
			"prices",
			"insufficient_inventory",
			"data",
			"metadata",
		):
			self.assertNotIn(column, StoreCartShippingOption.model_fields)

	def test_serializes_to_json_ready_values(self):
		entry = option(
			amount=50,
			calculated_price=StoreCalculatedPrice(calculated_amount=50, currency_code="th"),
		)
		dumped = entry.model_dump(mode="json")
		self.assertEqual(
			dumped,
			{
				"id": "Dev Flat Rate",
				"name": "Dev Flat Rate",
				"price_type": "flat",
				"amount": 50,
				"calculated_price": {
					"is_calculated_price_price_list": None,
					"is_calculated_price_tax_inclusive": None,
					"calculated_amount": 50,
					"is_original_price_price_list": None,
					"is_original_price_tax_inclusive": None,
					"original_amount": None,
					"currency_code": "th",
					"is_calculated_price_promotion": None,
				},
			},
		)


if __name__ == "__main__":
	unittest.main()
