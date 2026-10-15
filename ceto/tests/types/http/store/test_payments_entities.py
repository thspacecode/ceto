import unittest
from datetime import datetime

from pydantic import ValidationError

from ceto.types.http.store.carts import StoreCart
from ceto.types.http.store.orders import StoreOrder
from ceto.types.http.store.payments import (
	PaymentCollectionStatus,
	PaymentSessionStatus,
	StorePaymentCollection,
	StorePaymentProvider,
	StorePaymentSession,
)

MINIMAL_COLLECTION = {
	"id": "pay_col_1",
	"currency_code": "thb",
	"amount": 1000.0,
	"status": "not_paid",
}

MINIMAL_SESSION = {
	"id": "payses_1",
	"amount": 1000.0,
	"currency_code": "thb",
	"provider_id": "pp_beam_beam",
	"data": {},
	"status": "pending",
}


class TestStorePaymentProvider(unittest.TestCase):
	def test_provider_is_id_only(self):
		self.assertEqual(StorePaymentProvider(id="pp_beam_beam").model_dump(), {"id": "pp_beam_beam"})

	def test_provider_requires_id(self):
		with self.assertRaises(ValidationError):
			StorePaymentProvider()


class TestStorePaymentSession(unittest.TestCase):
	def test_minimal_pinned_session_round_trips(self):
		session = StorePaymentSession.model_validate(MINIMAL_SESSION)
		self.assertEqual(session.id, "payses_1")
		self.assertEqual(session.provider_id, "pp_beam_beam")
		self.assertEqual(session.status, "pending")
		self.assertEqual(session.data, {})
		self.assertIsNone(session.context)
		self.assertIsNone(session.authorized_at)

	def test_session_data_defaults_to_an_empty_object(self):
		session = StorePaymentSession.model_validate(
			{key: value for key, value in MINIMAL_SESSION.items() if key != "data"}
		)
		self.assertEqual(session.data, {})

	def test_session_data_is_required_and_non_null(self):
		with self.assertRaises(ValidationError):
			StorePaymentSession.model_validate({**MINIMAL_SESSION, "data": None})

	def test_session_requires_provider_currency_and_status(self):
		for field in ("currency_code", "provider_id", "status"):
			payload = {key: value for key, value in MINIMAL_SESSION.items() if key != field}
			with self.subTest(field=field):
				with self.assertRaises(ValidationError):
					StorePaymentSession.model_validate(payload)

	def test_session_status_union_is_pinned(self):
		for status in PaymentSessionStatus.__args__:
			with self.subTest(status=status):
				StorePaymentSession.model_validate({**MINIMAL_SESSION, "status": status})
		with self.assertRaises(ValidationError):
			StorePaymentSession.model_validate({**MINIMAL_SESSION, "status": "partially_captured"})


class TestStorePaymentCollection(unittest.TestCase):
	def test_minimal_pinned_collection_round_trips(self):
		collection = StorePaymentCollection.model_validate(MINIMAL_COLLECTION)
		self.assertEqual(collection.status, "not_paid")
		self.assertEqual(collection.payment_sessions, [])
		self.assertEqual(collection.payment_providers, [])
		self.assertIsNone(collection.authorized_amount)
		self.assertIsNone(collection.captured_amount)
		self.assertIsNone(collection.refunded_amount)
		self.assertIsNone(collection.completed_at)

	def test_collection_requires_id_and_currency(self):
		for field in ("id", "currency_code"):
			payload = {key: value for key, value in MINIMAL_COLLECTION.items() if key != field}
			with self.subTest(field=field):
				with self.assertRaises(ValidationError):
					StorePaymentCollection.model_validate(payload)

	def test_amount_and_status_carry_serializer_friendly_defaults(self):
		# Money and status default like every Ceto entity does, so a
		# partially specified collection still validates (the pinned amount
		# and status are always written by the persistence layer).
		collection = StorePaymentCollection.model_validate({"id": "pay_col_1", "currency_code": "thb"})
		self.assertEqual(collection.amount, 0)
		self.assertEqual(collection.status, "not_paid")

	def test_collection_status_union_is_pinned(self):
		for status in PaymentCollectionStatus.__args__:
			with self.subTest(status=status):
				StorePaymentCollection.model_validate({**MINIMAL_COLLECTION, "status": status})
		with self.assertRaises(ValidationError):
			StorePaymentCollection.model_validate({**MINIMAL_COLLECTION, "status": "partially_refunded"})

	def test_collection_embeds_sessions_and_providers(self):
		collection = StorePaymentCollection.model_validate(
			{
				**MINIMAL_COLLECTION,
				"payment_providers": [{"id": "pp_beam_beam"}],
				"payment_sessions": [MINIMAL_SESSION],
			}
		)
		self.assertEqual(collection.payment_providers[0].id, "pp_beam_beam")
		self.assertEqual(collection.payment_sessions[0].provider_id, "pp_beam_beam")

	def test_timestamps_accept_datetimes(self):
		collection = StorePaymentCollection.model_validate(
			{
				**MINIMAL_COLLECTION,
				"created_at": datetime(2026, 10, 14, 8, 0, 0),
				"updated_at": datetime(2026, 10, 14, 8, 30, 0),
			}
		)
		self.assertEqual(collection.created_at, datetime(2026, 10, 14, 8, 0, 0))


class TestCartAndOrderExposure(unittest.TestCase):
	def test_store_cart_defaults_to_no_payment_collection(self):
		cart = StoreCart.model_validate({"id": "cart_1", "currency_code": "thb"})
		self.assertIsNone(cart.payment_collection)

	def test_store_cart_accepts_an_embedded_payment_collection(self):
		cart = StoreCart.model_validate(
			{
				"id": "cart_1",
				"currency_code": "thb",
				"payment_collection": {
					**MINIMAL_COLLECTION,
					"payment_sessions": [MINIMAL_SESSION],
				},
			}
		)
		self.assertEqual(cart.payment_collection.id, "pay_col_1")
		self.assertEqual(cart.payment_collection.payment_sessions[0].id, "payses_1")

	def test_store_order_defaults_to_no_payment_collections(self):
		order = StoreOrder.model_validate({"id": "order_1", "currency_code": "thb"})
		self.assertEqual(order.payment_collections, [])
		self.assertEqual(order.payment_status, "not_paid")

	def test_store_order_accepts_embedded_payment_collections(self):
		order = StoreOrder.model_validate(
			{"id": "order_1", "currency_code": "thb", "payment_collections": [MINIMAL_COLLECTION]}
		)
		self.assertEqual([collection.id for collection in order.payment_collections], ["pay_col_1"])

	def test_serialization_defaults_keep_the_contract_only_shape(self):
		# The cart/order serializers are untouched in this phase: dumping a
		# default-built cart/order must not grow payment payloads.
		cart = StoreCart.model_validate({"id": "c", "currency_code": "thb"})
		order = StoreOrder.model_validate({"id": "o", "currency_code": "thb"})
		self.assertNotIn("payment_collection", cart.model_dump(exclude_defaults=True))
		self.assertNotIn("payment_collections", order.model_dump(exclude_defaults=True))


if __name__ == "__main__":
	unittest.main()
