"""Pinned shipping-option entity and envelope contracts."""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.shipping_options import (
	StoreCartShippingOption,
	StoreShippingOptionCalculatedPrice,
	StoreShippingOptionListResponse,
	StoreShippingOptionProvider,
	StoreShippingOptionResponse,
)

#: The opaque option id of the contract decision: ``so_`` +
#: base64url(provider_id + ':' + option_key) — here the built-in
#: ``erpnext`` provider naming the ``Dev Flat Rate`` rule. Never the raw
#: rule name itself.
OPAQUE_ID = "so_ZXJwbmV4dDpEZXYgRmxhdCBSYXRl"


def option(**overrides):
	kwargs = {
		"id": OPAQUE_ID,
		"name": "Dev Flat Rate",
		"price_type": "flat",
		"provider": {"id": "erpnext", "is_enabled": True},
	}
	kwargs.update(overrides)
	return StoreCartShippingOption(**kwargs)


class TestStoreCartShippingOptionEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = option()
		self.assertEqual((entry.id, entry.name, entry.price_type), (OPAQUE_ID, "Dev Flat Rate", "flat"))
		self.assertEqual((entry.provider.id, entry.provider.is_enabled), ("erpnext", True))

	def test_the_public_id_is_the_opaque_so_token(self):
		# ``so_<base64url(provider_id + ':' + option_key)>`` — opaque and
		# stable, never the raw Shipping Rule name; the encoder belongs to
		# the behavior slice and the legacy raw names stay accepted only by
		# the existing cart apply surface.
		self.assertRegex(option().id, r"^so_[A-Za-z0-9_-]+$")

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-optional columns: the
		# rule master always carries name and label, the provider relation
		# is always derivable, and the provider subset carries both of its
		# columns.
		for column in ("id", "name", "price_type", "provider"):
			kwargs = {key: value for key, value in option().model_dump().items() if key != column}
			with self.subTest(column=column), self.assertRaises(ValidationError):
				StoreCartShippingOption(**kwargs)
		for nested in ("id", "is_enabled"):
			provider = {"id": "erpnext", "is_enabled": True}
			del provider[nested]
			with self.subTest(column=nested), self.assertRaises(ValidationError):
				option(provider=provider)

	def test_price_type_is_the_pinned_union(self):
		# Built-in rules always serve "flat" — every option is a
		# deterministic cart-specific quote, the resolved rule rate, never a
		# stored list price. The union itself stays the pinned one.
		self.assertEqual(option(price_type="calculated").price_type, "calculated")
		with self.assertRaises(ValidationError):
			option(price_type="dynamic")

	def test_the_rate_defaults_to_the_honest_empty_value(self):
		# The rate resolves against the cart; an unresolvable context serves
		# the itemless baseline 0 with no calculated_price, and the Selling
		# charge row carries no tax allocation, so is_tax_inclusive is False
		# — never made-up amounts (the cart shipping-method convention).
		entry = option()
		self.assertEqual(entry.amount, 0)
		self.assertFalse(entry.is_tax_inclusive)
		self.assertIsNone(entry.calculated_price)
		self.assertIsNone(entry.data)
		self.assertIsNone(entry.metadata)

	def test_calculated_price_is_the_shipping_specific_subset(self):
		# Not the products pricing model: every column here is required — a
		# shipping quote resolves against the cart — while the products
		# subset would serve pricing-module nulls the projection can fill.
		entry = option(
			amount=50,
			calculated_price=StoreShippingOptionCalculatedPrice(
				calculated_amount=50,
				original_amount=50,
				currency_code="usd",
				is_calculated_price_tax_inclusive=False,
			),
		)
		self.assertEqual(entry.amount, 50)
		self.assertEqual(entry.calculated_price.calculated_amount, 50)
		self.assertEqual(entry.calculated_price.original_amount, 50)
		self.assertEqual(entry.calculated_price.currency_code, "usd")
		self.assertFalse(entry.calculated_price.is_calculated_price_tax_inclusive)

	def test_the_calculated_price_subset_is_never_partial(self):
		# A half-filled quote is refused instead of pretending the
		# projection filled the rest.
		with self.assertRaises(ValidationError):
			StoreShippingOptionCalculatedPrice(calculated_amount=50, currency_code="usd")

	def test_data_and_metadata_stay_nullable_pinned_columns(self):
		# The upstream entity pins both object columns; Ceto has no ERPNext
		# source for them, so they default to null and are served null —
		# the model still carries their pinned object shape.
		entry = option(data={"carrier": "dhl"}, metadata={"batch": "x"})
		self.assertEqual(entry.data, {"carrier": "dhl"})
		self.assertEqual(entry.metadata, {"batch": "x"})

	def test_the_fulfillment_module_columns_are_dropped_not_stubbed(self):
		# No ERPNext source exists for the remaining fulfillment-module
		# surfaces, so they are absent from the model entirely (products
		# precedent): never optional Nones pretending to be a projection.
		# The provider relation and the nullable data/metadata columns are
		# the deliberate exceptions pinned by the contract decisions.
		self.assertEqual(
			set(StoreCartShippingOption.model_fields),
			{
				"id",
				"name",
				"price_type",
				"provider",
				"amount",
				"is_tax_inclusive",
				"calculated_price",
				"data",
				"metadata",
			},
		)
		for column in (
			"service_zone_id",
			"shipping_profile_id",
			"provider_id",
			"type",
			"prices",
			"insufficient_inventory",
		):
			self.assertNotIn(column, StoreCartShippingOption.model_fields)

	def test_serializes_to_json_ready_values(self):
		entry = option(
			amount=50,
			calculated_price=StoreShippingOptionCalculatedPrice(
				calculated_amount=50,
				original_amount=50,
				currency_code="usd",
				is_calculated_price_tax_inclusive=False,
			),
		)
		dumped = entry.model_dump(mode="json")
		self.assertEqual(
			dumped,
			{
				"id": OPAQUE_ID,
				"name": "Dev Flat Rate",
				"price_type": "flat",
				"provider": {"id": "erpnext", "is_enabled": True},
				"amount": 50,
				"is_tax_inclusive": False,
				"calculated_price": {
					"calculated_amount": 50,
					"original_amount": 50,
					"currency_code": "usd",
					"is_calculated_price_tax_inclusive": False,
				},
				"data": None,
				"metadata": None,
			},
		)


if __name__ == "__main__":
	unittest.main()
