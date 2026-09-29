import unittest

from pydantic import ValidationError

from ceto.types.http.store.carts import StoreCartAddPromotion, StoreCartPromotion, StoreCartRemovePromotion


class TestStoreCartAddPromotionPayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		payload = StoreCartAddPromotion(promo_codes=["SAVE10"])
		self.assertEqual(payload.promo_codes, ["SAVE10"])

	def test_accepts_multiple_entries_and_strips_whitespace(self):
		payload = StoreCartAddPromotion(promo_codes=[" SAVE10 ", "SAVE10"])
		self.assertEqual(payload.promo_codes, ["SAVE10", "SAVE10"])

	def test_rejects_empty_list(self):
		with self.assertRaises(ValidationError):
			StoreCartAddPromotion(promo_codes=[])

	def test_rejects_missing_promo_codes(self):
		with self.assertRaises(ValidationError):
			StoreCartAddPromotion()

	def test_rejects_blank_codes(self):
		with self.assertRaises(ValidationError):
			StoreCartAddPromotion(promo_codes=["  "])

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreCartAddPromotion(promo_codes=["SAVE10"], code="SAVE10")


class TestStoreCartRemovePromotionPayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		payload = StoreCartRemovePromotion(promo_codes=["SAVE10"])
		self.assertEqual(payload.promo_codes, ["SAVE10"])

	def test_rejects_empty_list(self):
		with self.assertRaises(ValidationError):
			StoreCartRemovePromotion(promo_codes=[])

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreCartRemovePromotion(promo_codes=["SAVE10"], cart={"id": "cart_1"})


class TestStoreCartPromotionEntity(unittest.TestCase):
	def test_shape_matches_serialized_coupon(self):
		promotion = StoreCartPromotion(id="Ceto SAVE10", code="SAVE10")
		self.assertEqual(
			promotion.model_dump(), {"id": "Ceto SAVE10", "code": "SAVE10", "is_automatic": False}
		)

	def test_cart_promotions_default_to_empty_typed_list(self):
		from ceto.types.http.store.carts.entities import StoreCart

		cart = StoreCart(id="cart_123", currency_code="usd")
		self.assertEqual(cart.promotions, [])
		cart.promotions.append(StoreCartPromotion(id="Ceto SAVE10", code="SAVE10"))
		self.assertEqual(cart.promotions[0].code, "SAVE10")


if __name__ == "__main__":
	unittest.main()
