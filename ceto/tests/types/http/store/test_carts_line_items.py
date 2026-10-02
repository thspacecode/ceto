import unittest

from pydantic import ValidationError

from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCartLineItem,
	StoreUpdateCartLineItem,
)


class TestAddCartLineItemPayload(unittest.TestCase):
	def test_accepts_minimal_payload(self):
		payload = StoreAddCartLineItem(variant_id=" variant-1 ", quantity=1)
		self.assertEqual(payload.variant_id, "variant-1")
		self.assertEqual(payload.quantity, 1)
		self.assertIsNone(payload.metadata)

	def test_accepts_metadata(self):
		payload = StoreAddCartLineItem(variant_id="variant-1", quantity=3, metadata={"gift": True})
		self.assertEqual(payload.metadata, {"gift": True})

	def test_rejects_zero_and_negative_quantity(self):
		for quantity in (0, -1):
			with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
				StoreAddCartLineItem(variant_id="variant-1", quantity=quantity)

	def test_rejects_missing_variant_id(self):
		with self.assertRaises(ValidationError):
			StoreAddCartLineItem(quantity=1)

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreAddCartLineItem(variant_id="variant-1", quantity=1, id="li_123")


class TestUpdateCartLineItemPayload(unittest.TestCase):
	def test_accepts_quantity_and_optional_metadata(self):
		payload = StoreUpdateCartLineItem(quantity=2)
		self.assertEqual(payload.quantity, 2)
		self.assertIsNone(payload.metadata)

	def test_rejects_zero_quantity(self):
		with self.assertRaises(ValidationError):
			StoreUpdateCartLineItem(quantity=0)

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreUpdateCartLineItem(quantity=1, variant_id="variant-1")


class TestLineItemDeleteResponse(unittest.TestCase):
	def test_exact_shape(self):
		from ceto.types.http.store.carts.responses import StoreLineItemDeleteResponse

		response = StoreLineItemDeleteResponse(id="li_123", parent="cart_123")
		self.assertEqual(
			response.model_dump(),
			{"id": "li_123", "object": "line-item", "deleted": True, "parent": "cart_123"},
		)

	def test_rejects_extra_fields(self):
		from ceto.types.http.store.carts.responses import StoreLineItemDeleteResponse

		with self.assertRaises(ValidationError):
			StoreLineItemDeleteResponse(id="li_123", parent="cart_123", cart={"id": "cart_123"})


class TestStoreCartLineItemEntity(unittest.TestCase):
	def test_defaults_match_current_serializer_output(self):
		item = StoreCartLineItem(id="li_123", cart_id="cart_123", quantity=2)
		dumped = item.model_dump()
		self.assertEqual(dumped["id"], "li_123")
		self.assertEqual(dumped["cart_id"], "cart_123")
		self.assertEqual(dumped["quantity"], 2)
		self.assertTrue(dumped["requires_shipping"])
		self.assertTrue(dumped["is_discountable"])
		self.assertEqual(dumped["unit_price"], 0)
		self.assertEqual(dumped["total"], 0)
		self.assertEqual(dumped["metadata"], None)

	def test_cart_items_default_to_empty_typed_list(self):
		from ceto.types.http.store.carts.entities import StoreCart

		cart = StoreCart(id="cart_123", currency_code="usd")
		self.assertEqual(cart.items, [])
		cart.items.append(StoreCartLineItem(id="li_123", cart_id="cart_123", quantity=1))
		self.assertEqual(cart.items[0].id, "li_123")


if __name__ == "__main__":
	unittest.main()
