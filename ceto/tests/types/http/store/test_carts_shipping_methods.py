import unittest
from datetime import datetime

from pydantic import ValidationError

from ceto.types.http.store.carts import (
	StoreAddCartShippingMethods,
	StoreCalculateCartTaxes,
	StoreCartShippingMethod,
)


class TestStoreAddCartShippingMethodsPayload(unittest.TestCase):
	def test_accepts_minimal_body(self):
		payload = StoreAddCartShippingMethods(option_id=" so_123 ")
		self.assertEqual(payload.option_id, "so_123")
		self.assertIsNone(payload.data)

	def test_accepts_option_data(self):
		payload = StoreAddCartShippingMethods(option_id="so_123", data={"carrier": "dhl"})
		self.assertEqual(payload.option_id, "so_123")
		self.assertEqual(payload.data, {"carrier": "dhl"})

	def test_rejects_missing_option_id(self):
		with self.assertRaises(ValidationError):
			StoreAddCartShippingMethods()

	def test_rejects_blank_option_id(self):
		with self.assertRaises(ValidationError):
			StoreAddCartShippingMethods(option_id="   ")

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreAddCartShippingMethods(option_id="so_123", cart_id="cart_123")


class TestStoreCalculateCartTaxesPayload(unittest.TestCase):
	def test_accepts_empty_body(self):
		payload = StoreCalculateCartTaxes()
		self.assertEqual(payload.model_dump(), {})

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreCalculateCartTaxes(cart_id="cart_123")


class TestStoreCartShippingMethodEntity(unittest.TestCase):
	@staticmethod
	def _method(**overrides):
		"""Build a fully populated method (pinned-required fields included)."""
		kwargs = {
			"id": "sm_123",
			"cart_id": "cart_123",
			"shipping_option_id": "Ceto Flat Rate",
			"name": "Flat Rate",
			"amount": 50,
			"subtotal": 50,
			"tax_total": 0,
			"total": 50,
			"is_tax_inclusive": False,
			"created_at": datetime(2024, 5, 1, 12, 0, 0),
			"updated_at": datetime(2024, 5, 2, 12, 0, 0),
		}
		kwargs.update(overrides)
		return StoreCartShippingMethod(**kwargs)

	def test_shape_matches_field_mapping_output(self):
		method = self._method(
			subtotal=50,
			tax_total=3.5,
			total=53.5,
		)
		self.assertEqual(
			method.model_dump(),
			{
				"id": "sm_123",
				"cart_id": "cart_123",
				"shipping_option_id": "Ceto Flat Rate",
				"name": "Flat Rate",
				"amount": 50,
				"subtotal": 50,
				"tax_total": 3.5,
				"total": 53.5,
				"is_tax_inclusive": False,
				"created_at": datetime(2024, 5, 1, 12, 0, 0),
				"updated_at": datetime(2024, 5, 2, 12, 0, 0),
			},
		)

	def test_pinned_required_fields_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-optional columns.
		pinned = {
			"is_tax_inclusive": False,
			"created_at": datetime(2024, 5, 1, 12, 0, 0),
			"updated_at": datetime(2024, 5, 2, 12, 0, 0),
		}
		for field in pinned:
			kwargs = {
				"id": "sm_123",
				"cart_id": "cart_123",
				"name": "Flat Rate",
				**{key: value for key, value in pinned.items() if key != field},
			}
			with self.assertRaises(ValidationError, msg=field):
				StoreCartShippingMethod(**kwargs)
		populated = StoreCartShippingMethod(id="sm_123", cart_id="cart_123", name="Flat Rate", **pinned)
		self.assertFalse(populated.is_tax_inclusive)

	def test_unpopulated_fields_default_to_unset(self):
		method = self._method(shipping_option_id=None, amount=0, subtotal=0, total=0, tax_total=0)
		self.assertIsNone(method.shipping_option_id)
		self.assertEqual(method.amount, 0)
		self.assertEqual(method.subtotal, 0)
		self.assertEqual(method.total, 0)
		self.assertEqual(method.tax_total, 0)

	def test_serializes_to_json_ready_values(self):
		method = self._method(shipping_option_id=None)
		dumped = method.model_dump(mode="json")
		self.assertEqual(dumped["amount"], 50)
		self.assertEqual(dumped["shipping_option_id"], None)
		self.assertIs(dumped["is_tax_inclusive"], False)
		self.assertEqual(dumped["created_at"], "2024-05-01T12:00:00")
		self.assertEqual(dumped["updated_at"], "2024-05-02T12:00:00")

	def test_cart_shipping_methods_default_to_empty_typed_list(self):
		from ceto.types.http.store.carts.entities import StoreCart

		cart = StoreCart(id="cart_123", currency_code="usd")
		self.assertEqual(cart.shipping_methods, [])
		cart.shipping_methods.append(self._method())
		self.assertEqual(cart.shipping_methods[0].name, "Flat Rate")


if __name__ == "__main__":
	unittest.main()
