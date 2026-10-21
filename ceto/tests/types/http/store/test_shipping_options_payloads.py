"""Pinned shipping-option request body contracts.

Pins ``StoreCalculateShippingOptionPrice`` — the only bodyful
shipping-option route — against ``@medusajs/types@2.21.1``: the required
``cart_id`` and the optional provider ``data``, which is accepted for
request compatibility only and never persisted (the cart shipping-methods
``data`` seam).
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.shipping_options import StoreCalculateShippingOptionPrice


class TestStoreCalculateShippingOptionPricePayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		payload = StoreCalculateShippingOptionPrice(cart_id=" cart_123 ")
		self.assertEqual(payload.cart_id, "cart_123")
		self.assertIsNone(payload.data)
		self.assertEqual(payload.model_dump(), {"cart_id": "cart_123", "data": None})

	def test_accepts_provider_data(self):
		payload = StoreCalculateShippingOptionPrice(cart_id="cart_123", data={"carrier": "dhl"})
		self.assertEqual(payload.cart_id, "cart_123")
		self.assertEqual(payload.data, {"carrier": "dhl"})

	def test_cart_id_is_required_and_never_blank(self):
		with self.assertRaises(ValidationError):
			StoreCalculateShippingOptionPrice()
		for blank in ("", "   "):
			with self.subTest(blank=blank), self.assertRaises(ValidationError):
				StoreCalculateShippingOptionPrice(cart_id=blank)

	def test_data_must_be_an_object(self):
		with self.assertRaises(ValidationError):
			StoreCalculateShippingOptionPrice(cart_id="cart_123", data=["dhl"])

	def test_rejects_extra_fields(self):
		for extra in (
			{"option_id": "so_ZXJwbmV4dDpEZXZfRmxhdF9SYXRl"},
			{"is_return": False},
			{"id": "cart_1"},
		):
			with self.subTest(extra=extra), self.assertRaises(ValidationError):
				StoreCalculateShippingOptionPrice(cart_id="cart_123", **extra)


if __name__ == "__main__":
	unittest.main()
