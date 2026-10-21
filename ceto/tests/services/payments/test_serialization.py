"""The payment serialization projections onto the pinned surface.

``PaymentSerializer`` serves the pinned ``StorePaymentCollection`` from the
Ceto payment records and projects the order-facing ``payment_status`` from
the current session alone. These tests pin: the null/empty defaults for
carts without payments, the collection shape (sessions oldest first, the
distinct provider identities), the money columns derived from the current
session's proven state, and the honest status projection — captured and
authorized are reported, everything else stays ``not_paid``.
"""

import frappe

from ceto.services.carts.quotation import CartService
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.serialization import PaymentSerializer
from ceto.services.payments.sessions import PaymentSessions
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.services.payments.test_sessions import (
	BEAM,
	STRIPE,
	StubProvider,
	session_payload,
	stub_registry,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class RecordingCharger:
	def __init__(self, status: str) -> None:
		self.response = {"payment_id": "attempt_1", "status": status}

	def __call__(self, request):
		return self.response


class TestPaymentSerialization(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.reference, self.quotation = CartService().create(StoreCreateCart(email="guest@example.com"))
		self.quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()

	def _collection(self) -> "frappe._dict":
		return PaymentCollections.ensure_collection(self.reference.cart_id)

	def _book(self, provider: str = BEAM, status: str = "Pending"):
		collection = PaymentCollections.ensure_collection(self.reference.cart_id)
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM), StubProvider(STRIPE)),
			create_payment=RecordingCharger(status),
		)
		return service.initialize_session(collection.payment_collection_id, session_payload(provider))

	def test_a_cart_without_a_collection_serves_null(self):
		self.assertIsNone(PaymentSerializer.for_cart(self.reference.cart_id))
		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "not_paid")
		self.assertEqual(
			PaymentSerializer.for_carts([self.reference.cart_id]), {self.reference.cart_id: None}
		)

	def test_the_collection_shape_with_its_sessions_and_providers(self):
		self._book(BEAM)
		self._book(STRIPE)
		collection = PaymentSerializer.for_cart(self.reference.cart_id)

		self.assertEqual(collection.id, self._collection().payment_collection_id)
		self.assertEqual(collection.currency_code, self.quotation.currency.lower())
		self.assertEqual(collection.amount, frappe.utils.flt(self.quotation.grand_total))
		self.assertEqual(collection.status, "not_paid")
		self.assertEqual([session.provider_id for session in collection.payment_sessions], [BEAM, STRIPE])
		# Oldest first; only the live session is current, and both providers
		# the sessions named are the collection's provider identities.
		self.assertEqual([provider.id for provider in collection.payment_providers], sorted([BEAM, STRIPE]))
		self.assertIsNone(collection.authorized_amount)
		self.assertIsNone(collection.captured_amount)
		self.assertIsNone(collection.refunded_amount)
		self.assertIsNone(collection.completed_at)
		self.assertIsNotNone(collection.created_at)
		self.assertIsNotNone(collection.updated_at)

	def test_session_payload_rides_the_session_data(self):
		self._book(BEAM)
		session = PaymentSerializer.for_cart(self.reference.cart_id).payment_sessions[0]

		self.assertEqual(session.id[:7], "payses_")
		self.assertEqual(session.data, {"payment_id": "attempt_1", "status": "Pending"})
		self.assertIsNone(session.context)
		self.assertIsNone(session.authorized_at)
		self.assertEqual(session.amount, frappe.utils.flt(self.quotation.grand_total))
		self.assertEqual(session.currency_code, self.quotation.currency.lower())

	def test_money_columns_follow_the_current_session_state(self):
		self._book(BEAM, status="Pending")
		pending = PaymentSerializer.for_cart(self.reference.cart_id)
		self.assertIsNone(pending.authorized_amount)
		self.assertIsNone(pending.captured_amount)

		authorized = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger("Pending")
		)
		collection = PaymentCollections.ensure_collection(self.reference.cart_id)
		session = authorized.initialize_session(
			collection.payment_collection_id, session_payload(BEAM)
		).payment_sessions[-1]
		frappe.db.set_value("Ceto Payment Session", session.id, "status", "authorized")

		after = PaymentSerializer.for_cart(self.reference.cart_id)
		self.assertEqual(after.authorized_amount, after.amount)
		self.assertIsNone(after.captured_amount)

	def test_a_captured_session_shows_both_money_columns(self):
		self._book(BEAM, status="Succeeded")
		collection = PaymentSerializer.for_cart(self.reference.cart_id)

		self.assertEqual(collection.status, "completed")
		self.assertEqual(collection.authorized_amount, collection.amount)
		self.assertEqual(collection.captured_amount, collection.amount)

	def test_the_payment_status_projection_reports_proven_money_only(self):
		self._book(BEAM, status="Pending")
		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "not_paid")

		settled = PaymentCollections.ensure_collection(self.reference.cart_id)
		session = (
			PaymentSessions(
				registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger("Succeeded")
			)
			.initialize_session(settled.payment_collection_id, session_payload(BEAM))
			.payment_sessions[-1]
		)
		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "captured")

		frappe.db.set_value("Ceto Payment Session", session.id, "status", "authorized")
		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "authorized")

		frappe.db.set_value("Ceto Payment Session", session.id, "status", "error")
		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "not_paid")

	def test_a_stale_paid_session_proves_nothing(self):
		self._book(BEAM, status="Succeeded")
		# The cart total changes; the fresh session is pending again.
		self.quotation.items[0].qty = 3
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		self._book(BEAM, status="Pending")

		self.assertEqual(PaymentSerializer.payment_status(self.reference.cart_id), "not_paid")
		collection = PaymentSerializer.for_cart(self.reference.cart_id)
		self.assertEqual(collection.status, "not_paid")
		self.assertIsNone(collection.authorized_amount)

	def test_bulk_reads_answer_the_single_cart_read(self):
		self._book(BEAM, status="Succeeded")
		single = PaymentSerializer.for_cart(self.reference.cart_id)

		bulk = PaymentSerializer.for_carts([self.reference.cart_id, "cart_other"])
		self.assertEqual(bulk[self.reference.cart_id].model_dump(mode="json"), single.model_dump(mode="json"))
		self.assertIsNone(bulk["cart_other"])

		self.assertEqual(
			PaymentSerializer.payment_statuses([self.reference.cart_id, "cart_other"]),
			{self.reference.cart_id: "captured", "cart_other": "not_paid"},
		)

	def test_empty_bulk_input_is_safe(self):
		self.assertEqual(PaymentSerializer.for_carts([]), {})
		self.assertEqual(PaymentSerializer.payment_statuses([]), {})
