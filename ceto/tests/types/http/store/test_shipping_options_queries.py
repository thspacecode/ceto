"""Pinned shipping-option query parameter contracts.

Pins the required ``cart_id`` scope of the cart-scoped list, the optional
``is_return`` flag and the unknown-parameter strictness of the Ceto read
models against the pinned ``@medusajs/types@2.21.1`` query types
(``http/shipping-option/store``): the dead ``FindParams`` pagination (the
pinned route ignores the page and the envelope carries none), the
``fields`` selector, the ``order`` sort and the ``$and``/``$or``
combinators are refused everywhere; ``is_return=true`` is a valid query
whose behavior slice later serves the empty option set — ERPNext
``Selling`` rules have no return-rate source, so no return option can ever
be listed.
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
		self.assertEqual(params.model_dump(), {"cart_id": "cart_123", "is_return": None})

	def test_cart_id_is_required_and_never_blank(self):
		with self.assertRaises(ValidationError):
			StoreGetShippingOptionList()
		for blank in ("", "   "):
			with self.subTest(blank=blank), self.assertRaises(ValidationError):
				StoreGetShippingOptionList(cart_id=blank)

	def test_is_return_is_optional_and_defaults_to_the_outbound_listing(self):
		# The pinned validator carries is_return beside cart_id; Ceto keeps
		# it optional, absent meaning the outbound listing.
		self.assertIsNone(StoreGetShippingOptionList(cart_id="cart_1").is_return)
		self.assertIs(StoreGetShippingOptionList(cart_id="cart_1", is_return=False).is_return, False)

	def test_is_return_true_later_serves_the_empty_option_set(self):
		# ERPNext Selling rules price outbound deliveries only — there is no
		# return-rate source, so is_return=true stays a valid query whose
		# behavior slice serves the empty option set instead of an error.
		for is_return in (True, "true", "1"):
			with self.subTest(is_return=is_return):
				self.assertIs(
					StoreGetShippingOptionList(cart_id="cart_1", is_return=is_return).is_return, True
				)

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
