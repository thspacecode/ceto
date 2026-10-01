"""Pinned completion contracts for ``POST /store/carts/{id}/complete``.

Phase 6 pins the request body and the ``StoreCompleteCartResponse`` union of
the pinned ``HttpTypes`` of ``@medusajs/types@2.21.1``: a successful
completion carries the placed ``order``, a failed one echoes the cart with a
structured ``error`` object. The completion service implements the contract
(``ceto/services/carts/completion.py``) and the route serves it
(``ceto.api.store.carts.complete_cart``).
"""

import unittest

from pydantic import TypeAdapter, ValidationError

from ceto.types.http.store.carts import (
	StoreCart,
	StoreCompleteCart,
	StoreCompleteCartError,
	StoreCompleteCartResponse,
)
from ceto.types.http.store.carts.responses import (
	StoreCompleteCartFailure,
	StoreCompleteCartSuccess,
)
from ceto.types.http.store.orders import StoreOrder

CART = StoreCart(id="cart_1", currency_code="usd")
ORDER = StoreOrder(id="order_1", currency_code="usd")
ERROR = {"message": "Payment not ready", "name": "PaymentReadinessError", "type": "payment_error"}


class TestStoreCompleteCartPayload(unittest.TestCase):
	def test_body_is_empty_by_default(self):
		payload = StoreCompleteCart()
		self.assertIsNone(payload.idempotency_key)
		self.assertEqual(payload.model_dump(), {"idempotency_key": None})

	def test_accepts_optional_idempotency_key(self):
		payload = StoreCompleteCart(idempotency_key=" idem-1 ")
		self.assertEqual(payload.idempotency_key, "idem-1")

	def test_rejects_unknown_fields(self):
		with self.assertRaises(ValidationError):
			StoreCompleteCart(payment={"provider": "x"})


class TestStoreCompleteCartResponse(unittest.TestCase):
	adapter = TypeAdapter(StoreCompleteCartResponse)

	def test_order_member_discriminates_on_type(self):
		response = self.adapter.validate_python({"type": "order", "order": ORDER.model_dump()})
		self.assertIsInstance(response, StoreCompleteCartSuccess)
		self.assertEqual(response.type, "order")
		self.assertEqual(response.order.id, "order_1")

	def test_cart_member_discriminates_on_type(self):
		response = self.adapter.validate_python({"type": "cart", "cart": CART.model_dump(), "error": ERROR})
		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.type, "cart")
		self.assertEqual(response.cart.id, "cart_1")
		self.assertEqual(response.error.message, "Payment not ready")
		self.assertEqual(response.error.name, "PaymentReadinessError")
		self.assertEqual(response.error.type, "payment_error")

	def test_type_is_the_discriminator(self):
		for body in (
			{"type": "order"},
			{"type": "cart", "cart": CART.model_dump()},
			{"type": "refund", "order": ORDER.model_dump()},
		):
			with self.subTest(body=body), self.assertRaises(ValidationError):
				self.adapter.validate_python(body)

	def test_error_object_requires_message_name_and_type(self):
		for partial in (
			{"name": "E", "type": "payment_error"},
			{"message": "Payment not ready", "type": "payment_error"},
			{"message": "Payment not ready", "name": "E"},
		):
			body = {"type": "cart", "cart": CART.model_dump(), "error": partial}
			with self.subTest(error=partial), self.assertRaises(ValidationError):
				self.adapter.validate_python(body)

	def test_members_carry_their_defaults_when_constructed(self):
		self.assertEqual(StoreCompleteCartSuccess(order=ORDER).type, "order")
		failure = StoreCompleteCartFailure(cart=CART, error=StoreCompleteCartError(**ERROR))
		self.assertEqual(failure.type, "cart")
		self.assertEqual(failure.model_dump()["error"], ERROR)


if __name__ == "__main__":
	unittest.main()
