"""Payment session orchestration: locking, idempotency and stable charging.

``PaymentSessions`` is the service behind the two collection routes. These
tests pin, against real cart fixtures: the cart-row-lock discipline with the
publishable-key guard; the upsert semantics of collection creation; the
idempotent session booking; the provider charge application — provider data
persisted, terminal attempt statuses projected, absence and failure stable —
and the masking of unknown and foreign resources.
"""

import json
from typing import Any

import frappe

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import InvalidDataError, NotAllowedError, RouteNotFoundError
from ceto.services.carts.quotation import CartService
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.gateway import ProviderChargeRequest
from ceto.services.payments.providers import ProviderRegistry
from ceto.services.payments.sessions import PaymentSessions
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart
from ceto.types.http.store.payments import StoreInitializePaymentSession

BEAM = "pp_beam_beam"
STRIPE = "pp_stripe_stripe"


class StubProvider:
	"""A registry provider whose enabled state the test controls."""

	def __init__(self, provider_id: str, enabled: bool = True) -> None:
		self.provider_id = provider_id
		self.enabled = enabled

	@property
	def id(self) -> str:
		return self.provider_id

	def is_enabled(self) -> bool:
		return self.enabled


def stub_registry(*providers: StubProvider) -> ProviderRegistry:
	return ProviderRegistry(providers)


class RecordingCharger:
	"""A stub paygi boundary recording its requests, answering a script."""

	def __init__(self, responses: list[Any]) -> None:
		self.responses = list(responses)
		self.requests: list[ProviderChargeRequest] = []

	def __call__(self, request: ProviderChargeRequest) -> Any:
		self.requests.append(request)
		return self.responses.pop(0)


def session_payload(provider_id: str = BEAM, data: dict | None = None) -> StoreInitializePaymentSession:
	return StoreInitializePaymentSession(provider_id=provider_id, data=data)


class TestPaymentSessions(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.reference, self.quotation = self._make_cart()

	def _make_cart(self, *, priced: bool = True):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = CartService().create(StoreCreateCart(email="guest@example.com"))
		if priced:
			self._price(reference, quotation)
		return reference, quotation

	def _price(self, reference, quotation, qty: int = 1) -> None:
		quotation.append("items", {"item_code": self.masters.item, "qty": qty})
		quotation.flags.ignore_mandatory = True
		quotation.save(ignore_permissions=True)
		quotation.reload()

	def _sessions(self, cart_id: str) -> list[str]:
		collection = PaymentCollections.current_collection(cart_id)
		if collection is None:
			return []
		return frappe.get_all(
			"Ceto Payment Session", filters={"payment_collection": collection.name}, pluck="name"
		)

	# --- collection creation -------------------------------------------------

	def test_create_collection_upserts_one_collection_per_cart(self):
		service = PaymentSessions()
		first = service.create_collection(self.reference.cart_id)
		second = service.create_collection(self.reference.cart_id)

		self.assertEqual(first.id, second.id)
		self.assertEqual(first.currency_code, self.quotation.currency.lower())
		self.assertEqual(first.amount, frappe.utils.flt(self.quotation.grand_total))
		self.assertEqual(first.status, "not_paid")
		self.assertEqual(first.payment_sessions, [])
		self.assertEqual(len(self._sessions(self.reference.cart_id)), 0)

	def test_create_collection_runs_the_guard_inside_the_lock(self):
		observed = {}

		def guard(reference):
			observed["cart_id"] = reference.cart_id
			raise NotAllowedError("wrong region")

		with self.assertRaises(NotAllowedError):
			PaymentSessions().create_collection(self.reference.cart_id, guard=guard)
		self.assertEqual(observed["cart_id"], self.reference.cart_id)
		# The scope refusal leaves no payment state behind.
		self.assertIsNone(PaymentCollections.current_collection(self.reference.cart_id))

	def test_create_collection_of_a_zero_payable_cart_is_refused(self):
		reference, _quotation = self._make_cart(priced=False)
		with self.assertRaises(InvalidDataError):
			PaymentSessions().create_collection(reference.cart_id)

	def test_unknown_cart_is_masked(self):
		with self.assertRaises(RouteNotFoundError):
			PaymentSessions().create_collection("cart_missing")

	def test_foreign_owned_cart_is_masked(self):
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_create_user() as email:
				with self.set_user(email):
					reference, _quotation = CartService().create(StoreCreateCart(email=email))
					owned = reference.cart_id
		with self.assertRaises(RouteNotFoundError):
			PaymentSessions().create_collection(owned)

	def _current_session(self, collection_id: str) -> "frappe._dict":
		return frappe.db.get_value(
			"Ceto Payment Session",
			{"payment_collection": collection_id, "is_current": 1},
			["payment_session_id", "provider_id", "amount", "currency_code", "status", "is_current"],
			as_dict=True,
		)

	# --- session creation ----------------------------------------------------

	def test_session_creation_books_charges_and_persists_the_provider_data(self):
		charger = RecordingCharger([{"payment_id": "attempt_1", "status": "Pending", "checkout_url": "u"}])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(len(charger.requests), 1)
		request = charger.requests[0]
		self.assertEqual(request.session_id, collection.payment_sessions[0].id)
		self.assertEqual(request.gateway, "beam")
		self.assertEqual(request.amount, collection.amount)
		self.assertEqual(request.currency_code, collection.currency_code)
		self.assertIsNone(request.data)

		(session_row,) = collection.payment_sessions
		self.assertEqual(
			session_row.data, {"payment_id": "attempt_1", "status": "Pending", "checkout_url": "u"}
		)
		self.assertEqual(session_row.status, "pending")
		self.assertEqual(collection.status, "not_paid")
		self.assertEqual(
			json.loads(frappe.db.get_value("Ceto Payment Session", session_row.id, "provider_data")),
			session_row.data,
		)

	def _collection_id(self) -> str:
		return PaymentCollections.ensure_collection(self.reference.cart_id).payment_collection_id

	def test_session_data_flows_to_the_provider_boundary(self):
		charger = RecordingCharger([{"payment_id": "attempt_1", "status": "Pending"}])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)
		payload = session_payload(BEAM, data={"type": "QR"})

		service.initialize_session(self._collection_id(), payload)

		self.assertEqual(charger.requests[0].data, {"type": "QR"})

	def test_succeeded_attempt_captures_the_session_and_completes_the_collection(self):
		charger = RecordingCharger([{"payment_id": "attempt_1", "status": "Succeeded"}])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(collection.payment_sessions[0].status, "captured")
		self.assertEqual(collection.status, "completed")
		self.assertEqual(
			frappe.db.get_value("Ceto Payment Session", collection.payment_sessions[0].id, "is_current"), 1
		)

	def test_failed_attempt_marks_the_session_error(self):
		charger = RecordingCharger([{"payment_id": "attempt_1", "status": "Failed"}])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(collection.payment_sessions[0].status, "error")

	def test_canceled_attempt_marks_the_session_canceled(self):
		charger = RecordingCharger([{"payment_id": "attempt_1", "status": "Canceled"}])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(collection.payment_sessions[0].status, "canceled")

	def test_in_flight_attempts_keep_the_session_pending(self):
		for status in ("Initiated", "Requires Action", "Pending", "Unknown"):
			with self.subTest(status=status):
				self.reference, self.quotation = self._make_cart()
				charger = RecordingCharger([{"payment_id": "attempt_1", "status": status}])
				service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)
				collection = service.initialize_session(self._collection_id(), session_payload(BEAM))
				self.assertEqual(collection.payment_sessions[0].status, "pending")

	def test_provider_absence_is_a_stable_pending_session(self):
		charger = RecordingCharger([None])
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(collection.payment_sessions[0].status, "pending")
		self.assertEqual(collection.payment_sessions[0].data, {})
		self.assertIsNone(
			frappe.db.get_value("Ceto Payment Session", collection.payment_sessions[0].id, "provider_data")
		)

	def test_provider_exception_is_a_stable_pending_session(self):
		def exploding(request):
			raise RuntimeError("gateway unreachable")

		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=exploding)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(collection.payment_sessions[0].status, "pending")
		self.assertEqual(collection.payment_sessions[0].data, {})

	def test_provider_timeout_is_a_stable_pending_session(self):
		def timing_out(request):
			raise TimeoutError("provider did not answer in time")

		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=timing_out)

		collection = service.initialize_session(self._collection_id(), session_payload(BEAM))

		# A timeout is a provider fault, not a route failure: no 500, the
		# session stays pending with no provider data, and the client can
		# retry the creation.
		self.assertEqual(collection.payment_sessions[0].status, "pending")
		self.assertEqual(collection.payment_sessions[0].data, {})
		self.assertIsNone(
			frappe.db.get_value("Ceto Payment Session", collection.payment_sessions[0].id, "provider_data")
		)

	def test_repeated_creation_reuses_the_session_and_recharges_idempotently(self):
		charger = RecordingCharger(
			[
				{"payment_id": "attempt_1", "status": "Pending"},
				{"payment_id": "attempt_1", "status": "Pending"},
			]
		)
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)

		first = service.initialize_session(self._collection_id(), session_payload(BEAM))
		second = service.initialize_session(self._collection_id(), session_payload(BEAM))

		self.assertEqual(first.payment_sessions[0].id, second.payment_sessions[0].id)
		self.assertEqual(len(self._sessions(self.reference.cart_id)), 1)
		# The boundary keyed both charges on the same session id.
		self.assertEqual(
			[request.session_id for request in charger.requests],
			[first.payment_sessions[0].id, second.payment_sessions[0].id],
		)

	def test_changed_amount_makes_the_session_stale_and_resets_the_collection(self):
		charger = RecordingCharger(
			[
				{"payment_id": "attempt_1", "status": "Succeeded"},
				{"payment_id": "attempt_2", "status": "Pending"},
			]
		)
		service = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)
		collection_id = self._collection_id()

		captured = service.initialize_session(collection_id, session_payload(BEAM))
		self.quotation.items[0].qty = 3
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		self.quotation.reload()
		fresh = service.initialize_session(collection_id, session_payload(BEAM))

		current = self._current_session(collection_id)
		self.assertNotEqual(current.payment_session_id, captured.payment_sessions[0].id)
		self.assertEqual(current.status, "pending")
		self.assertEqual(frappe.utils.flt(current.amount), fresh.amount)
		self.assertEqual(fresh.amount, frappe.utils.flt(self.quotation.grand_total))
		# The captured session is history; the collection tracks the fresh
		# unpaid attempt again.
		self.assertEqual(fresh.status, "not_paid")
		self.assertIsNone(fresh.authorized_amount)
		self.assertIsNone(fresh.captured_amount)
		stale = frappe.db.get_value(
			"Ceto Payment Session", captured.payment_sessions[0].id, ["status", "is_current"], as_dict=True
		)
		self.assertEqual(stale.status, "captured")
		self.assertEqual(stale.is_current, 0)

	def test_changed_provider_makes_the_session_stale(self):
		charger = RecordingCharger(
			[
				{"payment_id": "attempt_1", "status": "Pending"},
				{"payment_id": "attempt_2", "status": "Pending"},
			]
		)
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM), StubProvider(STRIPE)), create_payment=charger
		)
		collection_id = self._collection_id()

		first = service.initialize_session(collection_id, session_payload(BEAM))
		second = service.initialize_session(collection_id, session_payload(STRIPE))

		current = self._current_session(collection_id)
		self.assertNotEqual(current.payment_session_id, first.payment_sessions[0].id)
		self.assertEqual(current.provider_id, STRIPE)
		# The stale session is kept as a history row on the collection.
		self.assertEqual(len(second.payment_sessions), 2)
		self.assertEqual([session.provider_id for session in second.payment_sessions], [BEAM, STRIPE])

	def test_unknown_and_disabled_providers_are_refused_without_state(self):
		charger = RecordingCharger([])
		refused = PaymentSessions(registry=stub_registry(StubProvider(BEAM)), create_payment=charger)
		collection_id = self._collection_id()

		with self.assertRaises(InvalidDataError):
			refused.initialize_session(collection_id, session_payload("pp_unknown_unknown"))
		self._refused_disabled(collection_id)
		self.assertEqual(charger.requests, [])
		self.assertEqual(self._sessions(self.reference.cart_id), [])

	def _refused_disabled(self, collection_id: str) -> None:
		disabled = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM, enabled=False)), create_payment=RecordingCharger([])
		)
		with self.assertRaises(InvalidDataError):
			disabled.initialize_session(collection_id, session_payload(BEAM))

	def test_unknown_collection_id_is_masked(self):
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger([])
		)
		with self.assertRaises(RouteNotFoundError):
			service.initialize_session("pay_col_missing", session_payload(BEAM))

	def test_foreign_owned_cart_behind_a_collection_is_masked(self):
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_create_user() as email:
				with self.set_user(email):
					reference, quotation = CartService().create(StoreCreateCart(email=email))
			# Pricing runs outside the owner context, like every other test:
			# only the cart's ownership matters here.
			self._price(reference, quotation)
			owned = reference.cart_id
		PaymentCollections.ensure_collection(owned)
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger([])
		)
		collection_id = PaymentCollections.current_collection(owned).payment_collection_id

		with self.assertRaises(RouteNotFoundError):
			service.initialize_session(collection_id, session_payload(BEAM))

	def test_wrong_scoped_key_is_refused_inside_the_lock(self):
		service = PaymentSessions(
			registry=stub_registry(StubProvider(BEAM)), create_payment=RecordingCharger([])
		)
		collection_id = self._collection_id()
		scoped = CartPublishableKey(region_id="reg_other").check_reference

		with self.assertRaises(NotAllowedError):
			service.initialize_session(collection_id, session_payload(BEAM), guard=scoped)
		self.assertEqual(self._sessions(self.reference.cart_id), [])
