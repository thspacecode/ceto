"""Pinned transfer request bodies of the Store Order routes.

Phase 1 pins the three bodies the Phase 0 mapping confirmed
(``docs/orders/field-mapping.md``): the transfer request carries no recipient
identifier, accept and decline authorize with the single-use email-delivered
token, and cancel carries no body at all. Pure Python — no Frappe.
"""

import unittest

from pydantic import ValidationError

# The carts package initializes before the orders package (pre-existing
# cross-package import order constraint, see ``test_orders_manifest``).
import ceto.types.http.store.carts
from ceto.types.http.store.orders import (
	StoreAcceptOrderTransfer,
	StoreDeclineOrderTransfer,
	StoreRequestOrderTransfer,
)

TOKEN_BODIES = (StoreAcceptOrderTransfer, StoreDeclineOrderTransfer)


class TestStoreRequestOrderTransfer(unittest.TestCase):
	def test_body_is_empty_by_default(self):
		payload = StoreRequestOrderTransfer()
		self.assertIsNone(payload.description)
		self.assertIsNone(payload.update_order_email)
		self.assertEqual(payload.model_dump(), {"description": None, "update_order_email": None})

	def test_accepts_the_pinned_optional_fields(self):
		payload = StoreRequestOrderTransfer(description="Moving to my account", update_order_email=True)
		self.assertEqual(payload.description, "Moving to my account")
		self.assertTrue(payload.update_order_email)

	def test_carries_no_recipient_identifier(self):
		# Upstream pins no recipient: the authenticated customer requests
		# ownership for themselves and acceptance applies it from the stored
		# transfer record (Recorded Decision 9) — nothing may nominate one.
		self.assertEqual(set(StoreRequestOrderTransfer.model_fields), {"description", "update_order_email"})
		for field in ("customer_id", "recipient_id", "email", "to_customer_id"):
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreRequestOrderTransfer(**{field: "cust_1"})

	def test_rejects_unknown_fields(self):
		with self.assertRaises(ValidationError):
			StoreRequestOrderTransfer(token="tok_1")


class TestStoreTokenTransferBodies(unittest.TestCase):
	def test_token_is_required(self):
		for payload in TOKEN_BODIES:
			with self.subTest(payload=payload.__name__), self.assertRaises(ValidationError):
				payload()

	def test_token_rejects_blanks(self):
		# Mirrors the pinned z.string().min(1): blank and whitespace-only
		# tokens are invalid data, never a probing surface.
		for payload in TOKEN_BODIES:
			for token in ("", "   "):
				with self.subTest(payload=payload.__name__, token=token), self.assertRaises(ValidationError):
					payload(token=token)

	def test_strips_and_accepts_the_email_delivered_token(self):
		for payload in TOKEN_BODIES:
			with self.subTest(payload=payload.__name__):
				self.assertEqual(payload(token=" tok_1 ").token, "tok_1")

	def test_rejects_unknown_fields(self):
		for payload in TOKEN_BODIES:
			with self.subTest(payload=payload.__name__), self.assertRaises(ValidationError):
				payload(token="tok_1", description="nope")


if __name__ == "__main__":
	unittest.main()
