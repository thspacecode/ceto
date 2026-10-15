"""The completion payment gate: enforced/off policy, fail closed.

``cart_payment_ready`` is the hook registered under
``ceto_cart_payment_readiness``. With the policy ``off`` (the default) it
answers "no opinion" without reading a payment row; with ``enforced`` it
fails closed — only a current ``authorized``/``captured`` session still
matching the cart's live payable, for an enabled provider, lets a cart
complete. These tests drive the gate directly and through the real
completion service with the hook configuration ``ceto/hooks.py`` ships.
"""

import json
from unittest.mock import patch

import frappe

from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.providers import ProviderRegistry
from ceto.services.payments.readiness import cart_payment_ready
from ceto.services.payments.sessions import PaymentSessions
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.services.payments.test_sessions import (
	BEAM,
	StubProvider,
	session_payload,
	stub_registry,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCompleteCart, StoreCreateCart

ENFORCED = {"payment_policy": "enforced"}


class RecordingCharger:
	"""A stub paygi boundary answering one attempt status mapping."""

	def __init__(self, status: str) -> None:
		self.response = {"payment_id": "attempt_1", "status": status}

	def __call__(self, request):
		return self.response


def settled_status(response: str) -> PaymentSessions:
	return PaymentSessions(
		registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(response)
	)


def enabled_registry():
	"""The gate's registry seam, resolved to one enabled stub provider.

	paygi is deliberately absent on the test site, so the real registry
	answers "disabled" for everything — the gate's own fail-closed answer.
	The positive paths pin the verdicts *past* that boundary.
	"""
	return patch(
		"ceto.services.payments.readiness.default_registry", lambda: stub_registry(StubProvider(BEAM))
	)


class TestPaymentReadinessGate(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.reference, self.quotation = CartService().create(StoreCreateCart(email="guest@example.com"))
		self.quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()

	def _book_session(self, response: str = "Pending", registry=None) -> str:
		collection = PaymentCollections.ensure_collection(self.reference.cart_id)
		service = PaymentSessions(
			registry=registry or stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger(response)
		)
		session = service.initialize_session(
			collection.payment_collection_id,
			session_payload(BEAM),
		)
		return session.payment_sessions[-1].id

	def _gate(self):
		return cart_payment_ready(
			self.reference.cart_id,
			self.quotation.name,
			idempotency_key="complete-1",
		)

	def test_off_policy_answers_no_opinion_without_reading_payments(self):
		with patch("ceto.services.payments.readiness.frappe.db.get_value") as get_value:
			self.assertIsNone(self._gate())
		get_value.assert_not_called()

	def test_enforced_requires_a_collection(self):
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			self.assertFalse(self._gate())

	def test_enforced_requires_a_current_session(self):
		PaymentCollections.ensure_collection(self.reference.cart_id)
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			self.assertFalse(self._gate())

	def test_enforced_refuses_unpaid_states(self):
		for response in ("Pending", "Initiated", "Unknown", "Failed", "Canceled"):
			with self.subTest(status=response):
				collection = PaymentCollections.ensure_collection(self.reference.cart_id)
				settled_status(response).initialize_session(
					collection.payment_collection_id,
					session_payload(BEAM),
				)
				with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
					self.assertFalse(self._gate())

	def test_enforced_accepts_authorized_and_captured(self):
		self._book_session("Succeeded")
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			with enabled_registry():
				self.assertTrue(self._gate())

	def test_enforced_accepts_an_authorized_session(self):
		session_id = self._book_session("Pending")
		frappe.db.set_value("Ceto Payment Session", session_id, "status", "authorized")
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			with enabled_registry():
				self.assertTrue(self._gate())

	def test_enforced_refuses_a_stale_amount_or_currency(self):
		session_id = self._book_session("Succeeded")
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			with enabled_registry():
				self.assertTrue(self._gate())

			self.quotation.items[0].qty = 3
			self.quotation.flags.ignore_mandatory = True
			self.quotation.save(ignore_permissions=True)
			self.quotation.reload()
			# The cart grew: the paid session is stale and proves nothing.
			self.assertFalse(self._gate())

			frappe.db.set_value("Ceto Payment Session", session_id, "currency_code", "eur")
			self.assertFalse(self._gate())

	def test_enforced_refuses_an_unknown_or_disabled_provider(self):
		self._book_session("Succeeded")
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			# The stored session names a provider the registry dropped.
			with patch.object(ProviderRegistry, "resolve", return_value=None):
				self.assertFalse(self._gate())
			with patch.object(StubProvider, "is_enabled", return_value=False):
				self.assertFalse(self._gate())

	def test_enforced_fails_closed_when_the_check_itself_fails(self):
		self._book_session("Succeeded")
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			with patch(
				"ceto.services.payments.readiness.frappe.db.get_value",
				side_effect=RuntimeError("database gone"),
			):
				self.assertFalse(self._gate())

	def test_enforced_refuses_a_submitted_quotation(self):
		self._book_session("Succeeded")
		self.quotation.submit()
		with self.set_conf(ceto_cart={**self.masters.configuration, **ENFORCED}):
			self.assertFalse(self._gate())


class TestCompletionGateIntegration(CetoTestSuite):
	"""The gate wired into the real completion service through hooks.py."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.hooks = frappe.get_hooks("ceto_cart_payment_readiness", [])
		self.assertIn("ceto.services.payments.readiness.cart_payment_ready", self.hooks)
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"}},
		}

	def _prepared_cart(self) -> str:
		"""Create a checkout-ready cart (items, email, address, shipping)."""
		from werkzeug.test import EnvironBuilder
		from werkzeug.wrappers import Request

		import ceto.api.routes
		from ceto.routing import ceto_router

		def dispatch(method: str, path: str, payload: dict | None = None):
			builder = EnvironBuilder(
				path=path,
				method=method,
				data=json.dumps(payload) if payload is not None else None,
				content_type="application/json" if payload is not None else None,
				headers={"x-publishable-api-key": "pk_test"},
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			)
			request = Request(builder.get_environ())
			with self.set_request(request):
				response = ceto_router.dispatch(request)
			self.assertEqual(response.status_code, 200, response.get_json())
			return response.get_json()

		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			cart_id = dispatch("POST", "/ceto/store/carts?fields=id", {"email": "guest@example.com"})["cart"][
				"id"
			]
			dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items?fields=id",
				{"variant_id": self.masters.item, "quantity": 1},
			)
			dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}?fields=id",
				{
					"shipping_address": {
						"address_1": "1 Readiness Way",
						"city": "Bangkok",
						"country_code": "th",
					}
				},
			)
			dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id",
				{"option_id": self.masters.flat_rate_rule},
			)
		return cart_id

	def _complete(self, cart_id: str, *, policy: dict | None = None):
		with self.set_conf(ceto_cart={**self.configuration, **(policy or {})}), self.set_user("Guest"):
			return CartCompletion().complete(cart_id, StoreCompleteCart())

	def test_off_policy_completes_without_payment(self):
		cart_id = self._prepared_cart()
		result = self._complete(cart_id)
		self.assertEqual(result.type, "order")

	def test_enforced_refuses_a_pending_session_and_completes_a_captured_one(self):
		cart_id = self._prepared_cart()
		collection = PaymentCollections.ensure_collection(cart_id)
		settled_status("Pending").initialize_session(
			collection.payment_collection_id,
			session_payload(BEAM),
		)

		refused = self._complete(cart_id, policy=ENFORCED)
		self.assertEqual(refused.type, "cart")
		self.assertEqual(refused.error.name, "PaymentReadinessError")
		# Nothing was placed; the cart stays open and completable.
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name"))

		# The verified webhook captures the session; the very same cart now
		# completes under the same enforced policy.
		session_id = frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": collection.name, "is_current": 1},
			"name",
		)
		frappe.db.set_value("Ceto Payment Session", session_id, "status", "captured")
		frappe.db.set_value("Ceto Payment Collection", collection.name, "status", "completed")

		with enabled_registry():
			placed = self._complete(cart_id, policy=ENFORCED)
			self.assertEqual(placed.type, "order")

			# The placed order carries the authoritative payment projection:
			# the cart's collection with its captured session, and the
			# pinned payment_status derived from it.
			self.assertEqual(placed.order.payment_status, "captured")
			self.assertEqual(
				[paid.id for paid in placed.order.payment_collections], [collection.payment_collection_id]
			)
			(paid,) = placed.order.payment_collections
			self.assertEqual(paid.status, "completed")
			self.assertEqual(paid.captured_amount, paid.amount)
			self.assertEqual(paid.payment_sessions[0].status, "captured")

			# Exactly-once completion: the replay answers the same order.
			replayed = self._complete(cart_id, policy=ENFORCED)
			self.assertEqual(replayed.order.id, placed.order.id)
			self.assertEqual(len(frappe.get_all("Ceto Order Reference", filters={"cart_id": cart_id})), 1)
