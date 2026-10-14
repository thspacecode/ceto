"""Pinned shipping-option query parameter contracts.

Pins the required ``cart_id`` scope of the cart-scoped list and the
unknown-parameter strictness of the Ceto read models against the pinned
``@medusajs/types@2.21.1`` query types (``http/shipping-option/store``):
the dead ``FindParams`` pagination (the pinned route ignores the page and
the envelope carries none), the ``fields`` selector, the ``order`` sort,
the ``$and``/``$or`` combinators and ``is_return`` are refused everywhere.
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.shipping_options import (
	StoreGetShippingOptionList,
	StoreShippingOptionCalculateParams,
)


class TestStoreGetShippingOptionList(unittest.TestCase):
	def test_accepts_the_required_cart_scope(self):
		params = StoreGetShippingOptionList(cart_id=" cart_123 ")
		self.assertEqual(params.cart_id, "cart_123")
		self.assertEqual(params.model_dump(), {"cart_id": "cart_123"})

	def test_cart_id_is_required_and_never_blank(self):
		with self.assertRaises(ValidationError):
			StoreGetShippingOptionList()
		for blank in ("", "   "):
			with self.subTest(blank=blank), self.assertRaises(ValidationError):
				StoreGetShippingOptionList(cart_id=blank)

	def test_rejects_the_dead_pagination_and_upstream_surfaces(self):
		# The pinned 2.21.1 route validates the FindParams page (0/20) but
		# ignores it and its non-paginated envelope cannot carry it, so the
		# page keys are refused like every other unsupported surface.
		for query in (
			{"cart_id": "cart_1", "limit": 10},
			{"cart_id": "cart_1", "offset": 5},
			{"cart_id": "cart_1", "fields": "id,*service_zone"},
			{"cart_id": "cart_1", "order": "name"},
			{"cart_id": "cart_1", "$and": [{"cart_id": "cart_1"}]},
			{"cart_id": "cart_1", "$or": [{"cart_id": "cart_1"}]},
			{"cart_id": "cart_1", "stock_location_id": "sl_1"},
			{"cart_id": "cart_1", "region_id": "reg_1"},
			{"cart_id": "cart_1", "unknown": "x"},
		):
			with self.subTest(query=query), self.assertRaises(ValidationError):
				StoreGetShippingOptionList(**query)

	def test_is_return_is_refused_without_a_return_rate_source(self):
		# ERPNext Selling rules price outbound deliveries only; a return
		# option can never be served, so the flag is refused instead of
		# being accepted and silently ignored.
		for is_return in (True, False, "true", "false"):
			with self.subTest(is_return=is_return), self.assertRaises(ValidationError):
				StoreGetShippingOptionList(cart_id="cart_1", is_return=is_return)


class TestStoreShippingOptionCalculateParams(unittest.TestCase):
	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreShippingOptionCalculateParams().model_dump(), {})

	def test_carries_no_field_at_all(self):
		self.assertEqual(StoreShippingOptionCalculateParams.model_fields, {})

	def test_rejects_every_parameter(self):
		for query in (
			{"fields": "id,*type"},
			{"cart_id": "cart_1"},
			{"limit": "5"},
		):
			with self.subTest(query=query), self.assertRaises(ValidationError):
				StoreShippingOptionCalculateParams(**query)


if __name__ == "__main__":
	unittest.main()
