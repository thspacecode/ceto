"""Pinned ``StoreOrder`` subset for the completion response (Phase 6).

Mirrors ``StoreOrder`` of ``@medusajs/types@2.21.1`` for the columns the
completion serializer can derive from the mapped ERPNext Sales Order and the
completed cart's reference — and pins the deliberate omissions: the Medusa
display numbers (``display_id``, ``custom_display_id``) have no ERPNext
equivalent and the public order id is Ceto's own ``order_…`` id, while the
payment, fulfillment and summary surfaces stay out until their providers
exist.
"""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.carts import StoreCartAddress
from ceto.types.http.store.orders import (
	StoreOrder,
	StoreOrderAddress,
	StoreOrderLineItem,
	StoreOrderShippingMethod,
)


class TestStoreOrderEntity(unittest.TestCase):
	def test_constructs_with_identity_and_currency_only(self):
		order = StoreOrder(id="order_1", currency_code="usd")
		self.assertEqual(order.status, "pending")
		self.assertEqual(order.payment_status, "not_paid")
		self.assertEqual(order.fulfillment_status, "not_fulfilled")
		self.assertEqual(order.items, [])
		self.assertEqual(order.shipping_methods, [])
		self.assertIsNone(order.billing_address)
		self.assertIsNone(order.shipping_address)

	def test_totals_default_to_the_zeroed_cart_baseline(self):
		totals = StoreOrder(id="order_1", currency_code="usd").model_dump()
		for field in (
			"total",
			"subtotal",
			"tax_total",
			"discount_total",
			"discount_tax_total",
			"gift_card_total",
			"gift_card_tax_total",
			"credit_line_total",
			"shipping_total",
			"shipping_subtotal",
			"shipping_tax_total",
			"original_total",
			"original_subtotal",
			"original_tax_total",
			"original_item_total",
			"original_item_subtotal",
			"original_item_tax_total",
			"item_total",
			"item_subtotal",
			"item_tax_total",
			"original_shipping_total",
			"original_shipping_subtotal",
			"original_shipping_tax_total",
		):
			with self.subTest(field=field):
				self.assertEqual(totals[field], 0)

	def test_status_fields_accept_only_the_pinned_unions(self):
		order = StoreOrder(
			id="order_1",
			currency_code="usd",
			status="completed",
			payment_status="captured",
			fulfillment_status="shipped",
		)
		self.assertEqual(order.status, "completed")
		for field, value in (
			("status", "shelved"),
			("payment_status", "prepaid"),
			("fulfillment_status", "fulfil"),
		):
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreOrder(id="order_1", currency_code="usd", **{field: value})

	def test_display_ids_are_deliberately_omitted(self):
		order = StoreOrder(id="order_1", currency_code="usd")
		self.assertNotIn("display_id", StoreOrder.model_fields)
		self.assertNotIn("custom_display_id", StoreOrder.model_fields)
		self.assertNotIn("display_id", order.model_dump())
		self.assertNotIn("custom_display_id", order.model_dump())

	def test_discount_split_totals_are_deliberately_omitted(self):
		# The pinned StoreOrder of @medusajs/types@2.21.1 splits the discount
		# across item_discount_total and shipping_discount_total; ERPNext
		# carries a single order-level discount_amount (per-row discounts
		# ride the item rows) and gives the Shipping Rule charge no discount
		# bucket, so the split cannot be derived without inventing numbers.
		# discount_total keeps the order-level amount instead.
		order = StoreOrder(id="order_1", currency_code="usd")
		self.assertNotIn("item_discount_total", StoreOrder.model_fields)
		self.assertNotIn("shipping_discount_total", StoreOrder.model_fields)
		self.assertNotIn("item_discount_total", order.model_dump())
		self.assertNotIn("shipping_discount_total", order.model_dump())
		self.assertIn("discount_total", StoreOrder.model_fields)

	def test_provider_surfaces_stay_omitted(self):
		for field in (
			"version",
			"summary",
			"transactions",
			"payment_collections",
			"fulfillments",
			"customer",
		):
			with self.subTest(field=field):
				self.assertNotIn(field, StoreOrder.model_fields)

	def test_locale_is_a_cart_column_only(self):
		# The pinned StoreOrder of @medusajs/types@2.21.1 has no locale column
		# (StoreCart does), so the order serializer must never report one.
		self.assertNotIn("locale", StoreOrder.model_fields)
		self.assertNotIn("locale", StoreOrder(id="order_1", currency_code="usd").model_dump())

	def test_requires_identity_and_currency(self):
		with self.assertRaises(ValidationError):
			StoreOrder(currency_code="usd")
		with self.assertRaises(ValidationError):
			StoreOrder(id="order_1")


class TestStoreOrderCollections(unittest.TestCase):
	TIMESTAMP = datetime(2026, 10, 2, tzinfo=UTC)

	def test_line_item_requires_identity_and_quantity(self):
		line = StoreOrderLineItem(id="li_1", order_id="order_1", quantity=2)
		self.assertEqual(line.order_id, "order_1")
		self.assertEqual(line.unit_price, 0)
		based = {"id": "li_1", "order_id": "order_1", "quantity": 2}
		for field in ("id", "order_id", "quantity"):
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreOrderLineItem(**{**based, field: None})

	def test_shipping_method_requires_name_and_tax_mode(self):
		timestamped = {
			"id": "sm_1",
			"order_id": "order_1",
			"name": "Flat Rate",
			"is_tax_inclusive": False,
			"created_at": self.TIMESTAMP,
			"updated_at": self.TIMESTAMP,
		}
		method = StoreOrderShippingMethod(**timestamped)
		self.assertEqual(method.tax_total, 0)
		for field in ("name", "is_tax_inclusive", "created_at", "updated_at"):
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreOrderShippingMethod(**{**timestamped, field: None})

	def test_order_carries_items_and_shipping_methods(self):
		order = StoreOrder(
			id="order_1",
			currency_code="usd",
			items=[StoreOrderLineItem(id="li_1", order_id="order_1", quantity=1)],
			shipping_methods=[
				StoreOrderShippingMethod(
					id="sm_1",
					order_id="order_1",
					name="Flat Rate",
					is_tax_inclusive=False,
					created_at=self.TIMESTAMP,
					updated_at=self.TIMESTAMP,
				)
			],
		)
		self.assertEqual(len(order.items), 1)
		self.assertEqual(len(order.shipping_methods), 1)


class TestStoreOrderAddressEntity(unittest.TestCase):
	def test_reuses_the_cart_address_subset(self):
		# Both entities serialize the same cart-scoped ERPNext Address copy;
		# the order subclass exists for its own pinned name.
		self.assertTrue(issubclass(StoreOrderAddress, StoreCartAddress))
		address = StoreOrderAddress(id="addr_1", city="Bangkok", country_code="th")
		self.assertEqual(address.country_code, "th")
		self.assertIn("first_name", StoreOrderAddress.model_fields)
		self.assertIn("address_1", StoreOrderAddress.model_fields)


if __name__ == "__main__":
	unittest.main()
