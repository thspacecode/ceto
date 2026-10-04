"""Pinned response envelopes of the Store Order routes.

Phase 1 pins the response side only: retrieve and every transfer route
respond ``{order: StoreOrder}`` and the list responds the pinned
``{orders, count, offset, limit}`` envelope — deliberately without the
optional ``estimate_count`` the shared ``PaginatedResponse`` declares but
the orders list never emits (``docs/orders/field-mapping.md``). Pure Python
— no Frappe.
"""

import unittest

from pydantic import ValidationError

# The carts package initializes before the orders package (pre-existing
# cross-package import order constraint, see ``test_orders_manifest``).
import ceto.types.http.store.carts
from ceto.types.http.store.orders import (
	StoreOrder,
	StoreOrderListResponse,
	StoreOrderResponse,
)

ORDER = StoreOrder(id="order_1", currency_code="usd")


class TestStoreOrderResponse(unittest.TestCase):
	def test_carries_the_order(self):
		response = StoreOrderResponse(order=ORDER)
		self.assertEqual(response.order.id, "order_1")
		self.assertEqual(set(StoreOrderResponse.model_fields), {"order"})

	def test_validates_the_nested_order(self):
		response = StoreOrderResponse.model_validate({"order": {"id": "order_1", "currency_code": "usd"}})
		self.assertEqual(response.order.status, "pending")
		with self.assertRaises(ValidationError):
			StoreOrderResponse.model_validate({"order": {"id": "order_1"}})
		with self.assertRaises(ValidationError):
			StoreOrderResponse.model_validate({})


class TestStoreOrderListResponse(unittest.TestCase):
	def test_envelope_is_exactly_the_pinned_pagination(self):
		response = StoreOrderListResponse.model_validate(
			{"orders": [{"id": "order_1", "currency_code": "usd"}], "count": 1, "offset": 0, "limit": 50}
		)
		self.assertEqual([order.id for order in response.orders], ["order_1"])
		self.assertEqual((response.count, response.offset, response.limit), (1, 0, 50))
		self.assertEqual(
			set(StoreOrderListResponse.model_fields),
			{"orders", "count", "offset", "limit"},
		)

	def test_estimate_count_is_deliberately_omitted(self):
		# The pinned orders list handler never emits estimate_count and Ceto
		# has no index engine — the envelope must not grow one silently.
		self.assertNotIn("estimate_count", StoreOrderListResponse.model_fields)
		self.assertNotIn(
			"estimate_count",
			StoreOrderListResponse.model_validate(
				{"orders": [], "count": 0, "offset": 0, "limit": 50}
			).model_dump(),
		)

	def test_pagination_fields_are_required(self):
		body = {"orders": [], "count": 0, "offset": 0, "limit": 50}
		for key in ("orders", "count", "offset", "limit"):
			partial = {k: v for k, v in body.items() if k != key}
			with self.subTest(key=key), self.assertRaises(ValidationError):
				StoreOrderListResponse.model_validate(partial)


if __name__ == "__main__":
	unittest.main()
