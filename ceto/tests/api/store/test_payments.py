"""Phase 5C payment endpoints: ``GET /store/payment-providers`` and the two
collection routes through the real router.

Covers the HTTP surface: the publishable-key requirement on all three
routes, the strict provider-list query (required ``region_id``, the pinned
pagination defaults, no unknown keys, key-scope refusal), the masked
``404`` for unknown and foreign carts/collections, the upsert semantics,
the ``fields`` selection, the paygi-backed session happy path with its
idempotent repeat and — for provider absence, failure and terminal
statuses — the stable answers that must never turn into a ``500``.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so tests that expect an error
provision a fresh cart.
"""

import json
from unittest.mock import patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.payments.collections import PaymentCollections
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.services.payments.test_sessions import StubProvider, stub_registry
from ceto.tests.utils import CetoTestSuite

BEAM = "pp_beam_beam"
STRIPE = "pp_stripe_stripe"


def two_providers() -> "list[StubProvider]":
	return [StubProvider(BEAM), StubProvider(STRIPE)]


class RecordingCharger:
	"""A stub paygi boundary with a scripted status and call log."""

	def __init__(self, statuses: list) -> None:
		self.statuses = list(statuses)
		self.session_ids: list[str] = []

	def __call__(self, request):
		self.session_ids.append(request.session_id)
		return {"payment_id": "attempt_1", "status": self.statuses.pop(0), "checkout_url": "https://pay"}


class TestPaymentAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}

	def _dispatch(self, method: str, path: str, payload: dict | None = None, *, publishable_key="pk_test"):
		headers = {"x-publishable-api-key": publishable_key} if publishable_key else None
		builder = EnvironBuilder(
			path=path,
			method=method,
			data=json.dumps(payload) if payload is not None else None,
			content_type="application/json" if payload is not None else None,
			headers=headers,
			environ_base={"REMOTE_ADDR": "127.0.0.1"},
		)
		request = Request(builder.get_environ())
		with self.set_request(request):
			return ceto_router.dispatch(request)

	def _guest_cart(self, *, priced: bool = True) -> str:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			created = self._dispatch("POST", "/ceto/store/carts?fields=id", {"email": "guest@example.com"})
			self.assertEqual(created.status_code, 200)
			cart_id = created.get_json()["cart"]["id"]
			if priced:
				added = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/line-items?fields=id",
					{"variant_id": self.masters.item, "quantity": 1},
				)
				self.assertEqual(added.status_code, 200)
		return cart_id

	# --- GET /store/payment-providers ---------------------------------------

	def test_provider_list_requires_the_publishable_key(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"GET", "/ceto/store/payment-providers?region_id=reg", publishable_key=None
			)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_provider_list_needs_its_region(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", "/ceto/store/payment-providers")
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

			blank = self._dispatch("GET", "/ceto/store/payment-providers?region_id=")
			self.assertEqual(blank.status_code, 400)

	def test_provider_list_query_is_strict(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for query in (
				"region_id=reg&fields=id",
				"region_id=reg&order=id",
				"region_id=reg&limit=abc",
				"region_id=reg&limit=-1",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/payment-providers?{query}")
					self.assertEqual(response.status_code, 400)

	def test_provider_list_serves_the_pinned_envelope_and_pagination(self):
		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			patch("ceto.api.store.payments.default_registry", lambda: stub_registry(*two_providers())),
		):
			response = self._dispatch("GET", "/ceto/store/payment-providers?region_id=reg_test")
			self.assertEqual(response.status_code, 200)
			self.assertEqual(
				response.get_json(),
				{
					"payment_providers": [{"id": BEAM}, {"id": STRIPE}],
					"count": 2,
					"offset": 0,
					"limit": 20,
				},
			)

			paged = self._dispatch("GET", "/ceto/store/payment-providers?region_id=reg_test&limit=1&offset=1")
			self.assertEqual(
				paged.get_json(),
				{"payment_providers": [{"id": STRIPE}], "count": 2, "offset": 1, "limit": 1},
			)

	def test_provider_list_without_enabled_providers_is_an_empty_page(self):
		# paygi is not installed on the test site: the registry answers
		# "disabled" for everything — an empty page, never an error.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", "/ceto/store/payment-providers?region_id=reg_test")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json()["payment_providers"], [])
		self.assertEqual(response.get_json()["count"], 0)

	def test_provider_list_refuses_a_wrong_scoped_region(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch(
				"GET", "/ceto/store/payment-providers?region_id=reg_other", publishable_key="pk_test"
			)
		self.assertEqual(response.status_code, 403)

	# --- POST /store/payment-collections ------------------------------------

	def test_collection_create_upserts_and_derives_the_payable(self):
		cart_id = self._guest_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			first = self._dispatch(
				"POST", "/ceto/store/payment-collections?fields=id,currency_code", {"cart_id": cart_id}
			)
			self.assertEqual(first.status_code, 200)
			self.assertEqual(set(first.get_json()), {"payment_collection"})
			self.assertEqual(set(first.get_json()["payment_collection"]), {"id", "currency_code"})

			second = self._dispatch("POST", "/ceto/store/payment-collections", {"cart_id": cart_id})
			self.assertEqual(second.status_code, 200)
			collection = second.get_json()["payment_collection"]
			self.assertEqual(collection["id"], first.get_json()["payment_collection"]["id"])
			self.assertEqual(collection["currency_code"], "usd")
			self.assertGreater(collection["amount"], 0)
			self.assertEqual(collection["status"], "not_paid")
			self.assertEqual(collection["payment_sessions"], [])
			# One collection per cart lifetime, like Medusa's upsert.
			self.assertEqual(
				len(frappe.get_all("Ceto Payment Collection", filters={"cart_reference": cart_id})), 1
			)

			# The cart embeds its collection from now on.
			retrieved = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,payment_collection")
			self.assertEqual(retrieved.status_code, 200)
			embedded = retrieved.get_json()["cart"]["payment_collection"]
			self.assertEqual(embedded["id"], collection["id"])
			self.assertEqual(embedded["payment_sessions"], [])

	def test_a_cart_without_payments_embeds_a_null_collection(self):
		cart_id = self._guest_cart(priced=False)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			retrieved = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,payment_collection")
		self.assertEqual(retrieved.status_code, 200)
		self.assertIsNone(retrieved.get_json()["cart"]["payment_collection"])

	def test_collection_create_masks_unknown_and_foreign_carts(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			unknown = self._dispatch("POST", "/ceto/store/payment-collections", {"cart_id": "cart_missing"})
			self.assertEqual(unknown.status_code, 404)
			self.assertEqual(unknown.get_json()["type"], "not_found")

	def test_collection_create_refuses_a_wrong_scoped_key_without_state(self):
		cart_id = self._guest_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			refused = self._dispatch(
				"POST", "/ceto/store/payment-collections", {"cart_id": cart_id}, publishable_key="pk_other"
			)
		self.assertEqual(refused.status_code, 403)
		self.assertIsNone(PaymentCollections.current_collection(cart_id))

	def test_collection_create_body_is_strict(self):
		cart_id = self._guest_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for body in ({}, {"cart_id": cart_id, "extra": True}, {"cart_id": ""}):
				with self.subTest(body=body):
					response = self._dispatch("POST", "/ceto/store/payment-collections", body)
					self.assertEqual(response.status_code, 400)

	def test_collection_create_of_a_zero_payable_cart_is_refused(self):
		cart_id = self._guest_cart(priced=False)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/payment-collections", {"cart_id": cart_id})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	# --- POST /store/payment-collections/{id}/payment-sessions --------------

	def _collection_id(self, cart_id: str) -> str:
		with self.set_conf(ceto_cart=self.configuration):
			return PaymentCollections.ensure_collection(cart_id).payment_collection_id

	def _session_route(self, collection_id: str, body: dict, query: str = "", **kwargs):
		return self._dispatch(
			"POST",
			f"/ceto/store/payment-collections/{collection_id}/payment-sessions{query}",
			body,
			**kwargs,
		)

	def _session_context(self, statuses: list):
		registry = patch(
			"ceto.services.payments.collections.default_registry", lambda: stub_registry(*two_providers())
		)
		boundary = patch("ceto.services.payments.gateway.create_payment", RecordingCharger(statuses))
		return registry, boundary

	def test_session_creation_books_and_charges_the_pinned_collection_answer(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context(["Pending"])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary as charger,
		):
			response = self._session_route(collection_id, {"provider_id": BEAM, "data": {"type": "QR"}})

		self.assertEqual(response.status_code, 200)
		collection = response.get_json()["payment_collection"]
		(session,) = collection["payment_sessions"]
		self.assertRegex(session["id"], r"^payses_[0-9a-f]{32}$")
		self.assertEqual(session["provider_id"], BEAM)
		self.assertEqual(session["status"], "pending")
		self.assertEqual(
			session["data"], {"payment_id": "attempt_1", "status": "Pending", "checkout_url": "https://pay"}
		)
		self.assertIsNone(session["context"])
		self.assertIsNone(session["authorized_at"])
		# The collection answer carries the session and its provider.
		self.assertEqual(collection["status"], "not_paid")
		self.assertEqual([provider["id"] for provider in collection["payment_providers"]], [BEAM])
		self.assertEqual(charger.session_ids, [session["id"]])

	def test_repeated_session_creation_is_idempotent(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context(["Pending", "Pending"])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary as charger,
		):
			first = self._session_route(collection_id, {"provider_id": BEAM})
			second = self._session_route(collection_id, {"provider_id": BEAM})

		self.assertEqual(second.status_code, 200)
		self.assertEqual(
			second.get_json()["payment_collection"]["payment_sessions"][0]["id"],
			first.get_json()["payment_collection"]["payment_sessions"][0]["id"],
		)
		# Both charges keyed on the same session; one session row exists.
		self.assertEqual(charger.session_ids[0], charger.session_ids[1])
		self.assertEqual(
			len(frappe.get_all("Ceto Payment Session", filters={"payment_collection": collection_id})), 1
		)

	def test_session_creation_of_an_unknown_collection_is_masked(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._session_route("pay_col_missing", {"provider_id": BEAM})
		self.assertEqual(response.status_code, 404)

	def test_session_creation_with_an_unknown_provider_is_invalid_data(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context([])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary as charger,
		):
			response = self._session_route(collection_id, {"provider_id": "pp_unknown_unknown"})

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(charger.session_ids, [])
		self.assertIsNone(PaymentCollections.current_collection(cart_id))

	def test_session_creation_body_is_strict(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context([])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary,
		):
			for body in ({}, {"provider_id": BEAM, "unexpected": 1}):
				with self.subTest(body=body):
					response = self._session_route(collection_id, body)
					self.assertEqual(response.status_code, 400)

	def test_provider_absence_is_a_stable_pending_answer(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			patch(
				"ceto.services.payments.collections.default_registry",
				lambda: stub_registry(StubProvider(BEAM)),
			),
			patch("ceto.services.payments.gateway.create_payment", lambda request: None),
		):
			response = self._session_route(collection_id, {"provider_id": BEAM})

		self.assertEqual(response.status_code, 200)
		(session,) = response.get_json()["payment_collection"]["payment_sessions"]
		self.assertEqual(session["status"], "pending")
		self.assertEqual(session["data"], {})

	def test_provider_failure_never_becomes_a_500(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)

		def exploding(request):
			raise RuntimeError("gateway unreachable")

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			patch(
				"ceto.services.payments.collections.default_registry",
				lambda: stub_registry(StubProvider(BEAM)),
			),
			patch("ceto.services.payments.gateway.create_payment", exploding),
		):
			response = self._session_route(collection_id, {"provider_id": BEAM})

		self.assertEqual(response.status_code, 200)
		(session,) = response.get_json()["payment_collection"]["payment_sessions"]
		self.assertEqual(session["status"], "pending")
		self.assertEqual(session["data"], {})

	def test_a_failed_attempt_answers_with_an_error_session(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context(["Failed"])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary,
		):
			response = self._session_route(collection_id, {"provider_id": BEAM})

		self.assertEqual(response.status_code, 200)
		(session,) = response.get_json()["payment_collection"]["payment_sessions"]
		self.assertEqual(session["status"], "error")

	def test_a_captured_attempt_answers_with_the_completed_collection(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context(["Succeeded"])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary,
		):
			response = self._session_route(collection_id, {"provider_id": BEAM})

		self.assertEqual(response.status_code, 200)
		collection = response.get_json()["payment_collection"]
		self.assertEqual(collection["status"], "completed")
		(session,) = collection["payment_sessions"]
		self.assertEqual(session["status"], "captured")
		self.assertEqual(collection["captured_amount"], collection["amount"])

	def test_session_fields_selection_applies_to_the_collection(self):
		cart_id = self._guest_cart()
		collection_id = self._collection_id(cart_id)
		registry, boundary = self._session_context(["Pending"])

		with (
			self.set_conf(ceto_cart=self.configuration),
			self.set_user("Guest"),
			registry,
			boundary,
		):
			response = self._session_route(
				collection_id, {"provider_id": BEAM}, query="?fields=id,status,payment_sessions"
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()["payment_collection"]), {"id", "status", "payment_sessions"})
