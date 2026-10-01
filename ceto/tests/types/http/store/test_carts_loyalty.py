"""Pinned loyalty-plugin contracts for the cart gift-card and store-credit routes.

The routes are not part of the Medusa core Store API: the loyalty plugin owns
them (``@zjedene-medusa/loyalty-plugin@2.16.2``). These tests pin the request
payloads, the cart entity extensions and the manifest entries Ceto implements
against, including the two deliberate deviations: blank gift-card codes are
rejected and a provided store-credit amount must be positive.
"""

import unittest
from datetime import UTC, datetime, timezone

from pydantic import ValidationError

from ceto.types.http.store.carts import (
	StoreAddGiftCardToCart,
	StoreAddStoreCreditsToCart,
	StoreCart,
	StoreCartCreditLine,
	StoreCartGiftCard,
	StoreRemoveGiftCardFromCart,
)


class TestStoreAddGiftCardToCartPayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		self.assertEqual(StoreAddGiftCardToCart(code="GC-1234").code, "GC-1234")

	def test_strips_whitespace_from_code(self):
		self.assertEqual(StoreAddGiftCardToCart(code=" GC-1234 ").code, "GC-1234")

	def test_rejects_missing_code(self):
		with self.assertRaises(ValidationError):
			StoreAddGiftCardToCart()

	def test_rejects_blank_code(self):
		with self.assertRaises(ValidationError):
			StoreAddGiftCardToCart(code="   ")

	def test_rejects_extra_fields(self):
		# Pinned plugin validator: z.strictObject({ code }).
		with self.assertRaises(ValidationError):
			StoreAddGiftCardToCart(code="GC-1234", gift_card_codes=["GC-1234"])


class TestStoreRemoveGiftCardFromCartPayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		self.assertEqual(StoreRemoveGiftCardFromCart(code="GC-1234").code, "GC-1234")

	def test_rejects_missing_code(self):
		with self.assertRaises(ValidationError):
			StoreRemoveGiftCardFromCart()

	def test_rejects_blank_code(self):
		with self.assertRaises(ValidationError):
			StoreRemoveGiftCardFromCart(code=" ")

	def test_rejects_extra_fields(self):
		# Pinned plugin validator: z.strictObject({ code }).
		with self.assertRaises(ValidationError):
			StoreRemoveGiftCardFromCart(code="GC-1234", id="gc_1")


class TestStoreAddStoreCreditsToCartPayload(unittest.TestCase):
	def test_amount_is_optional(self):
		self.assertIsNone(StoreAddStoreCreditsToCart().amount)
		self.assertEqual(StoreAddStoreCreditsToCart(amount=25).amount, 25)

	def test_rejects_non_positive_amount(self):
		for amount in (0, -5):
			with self.subTest(amount=amount), self.assertRaises(ValidationError):
				StoreAddStoreCreditsToCart(amount=amount)

	def test_ignores_extra_fields(self):
		# Pinned plugin validator: z.object({ amount }) — the plugin strips
		# unknown fields instead of rejecting them, and Ceto mirrors that.
		payload = StoreAddStoreCreditsToCart(amount=5, store_credit_id="sca_1")
		self.assertEqual(payload.amount, 5)


class TestStoreCartLoyaltyEntities(unittest.TestCase):
	def test_cart_defaults_to_empty_loyalty_collections(self):
		cart = StoreCart(id="cart_1", currency_code="usd")
		self.assertEqual(cart.gift_cards, [])
		self.assertEqual(cart.credit_lines, [])

	def test_gift_card_entry_carries_exactly_the_code(self):
		self.assertEqual(StoreCartGiftCard(code="GC-1234").model_dump(), {"code": "GC-1234"})

	def test_credit_line_pins_the_plugin_reference_values(self):
		for reference, reference_id in (("gift-card", "gc_1"), ("store-credit", "sca_1")):
			with self.subTest(reference=reference):
				line = StoreCartCreditLine(
					id="cl_1",
					cart_id="cart_1",
					amount=10,
					reference=reference,
					reference_id=reference_id,
					created_at=datetime(2026, 10, 1, tzinfo=UTC),
					updated_at=datetime(2026, 10, 1, tzinfo=UTC),
				)
				self.assertEqual(line.reference, reference)
				self.assertEqual(line.reference_id, reference_id)

	def test_credit_line_rejects_unknown_reference(self):
		with self.assertRaises(ValidationError):
			StoreCartCreditLine(
				id="cl_1",
				cart_id="cart_1",
				amount=10,
				reference="coupon",
				reference_id="cp_1",
				created_at=datetime(2026, 10, 1, tzinfo=UTC),
				updated_at=datetime(2026, 10, 1, tzinfo=UTC),
			)

	def test_credit_line_rejects_missing_identity(self):
		with self.assertRaises(ValidationError):
			StoreCartCreditLine(cart_id="cart_1", amount=10, reference="gift-card", reference_id="gc_1")


if __name__ == "__main__":
	unittest.main()
