"""Pinned response envelopes of the Store shipping-option routes.

Phase 4 slice 1 pins the response side only: the list responds the exact
non-paginated ``{shipping_options}`` body of the pinned 2.21.1 list handler
— no ``count``/``offset``/``limit`` exists on the pinned envelope and none
may grow silently — and the calculate route responds
``{shipping_option: StoreCartShippingOption}``. Pure Python — no Frappe.
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.shipping_options import (
	StoreCartShippingOption,
	StoreShippingOptionListResponse,
	StoreShippingOptionResponse,
)

OPTION = StoreCartShippingOption(
	id="so_ZXJwbmV4dDpEZXZfRmxhdF9SYXRl",
	name="Dev Flat Rate",
	price_type="flat",
	provider={"id": "erpnext", "is_enabled": True},
)


class TestStoreShippingOptionListResponse(unittest.TestCase):
	def test_envelope_is_the_non_paginated_pinned_body(self):
		response = StoreShippingOptionListResponse.model_validate({"shipping_options": [OPTION.model_dump()]})
		self.assertEqual([entry.id for entry in response.shipping_options], [OPTION.id])
		self.assertEqual(set(StoreShippingOptionListResponse.model_fields), {"shipping_options"})

	def test_no_pagination_may_grow_on_the_list_envelope(self):
		# The pinned 2.21.1 list handler responds {shipping_options} only —
		# the dead validator page (0/20) must never leak into the envelope.
		for key in ("count", "offset", "limit"):
			self.assertNotIn(key, StoreShippingOptionListResponse.model_fields)
		response = StoreShippingOptionListResponse.model_validate(
			{"shipping_options": [], "count": 0, "offset": 0, "limit": 20}
		)
		self.assertEqual(response.model_dump(), {"shipping_options": []})

	def test_shipping_options_is_required(self):
		with self.assertRaises(ValidationError):
			StoreShippingOptionListResponse.model_validate({})


class TestStoreShippingOptionResponse(unittest.TestCase):
	def test_carries_the_option(self):
		response = StoreShippingOptionResponse(shipping_option=OPTION)
		self.assertEqual(response.shipping_option.id, OPTION.id)
		self.assertEqual(set(StoreShippingOptionResponse.model_fields), {"shipping_option"})

	def test_validates_the_nested_option(self):
		response = StoreShippingOptionResponse.model_validate(
			{
				"shipping_option": {
					"id": "so_ZXJwbmV4dDpGbGF0",
					"name": "Flat",
					"price_type": "calculated",
					"provider": {"id": "erpnext", "is_enabled": True},
				}
			}
		)
		self.assertEqual(response.shipping_option.price_type, "calculated")
		self.assertEqual(response.shipping_option.provider.id, "erpnext")
		with self.assertRaises(ValidationError):
			StoreShippingOptionResponse.model_validate(
				{
					"shipping_option": {
						"id": "so_ZXJwbmV4dDpGbGF0",
						"name": "Flat",
						"price_type": "calculated",
					}
				}
			)
		with self.assertRaises(ValidationError):
			StoreShippingOptionResponse.model_validate({})


if __name__ == "__main__":
	unittest.main()
