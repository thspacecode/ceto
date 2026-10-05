"""Phase 4/5 transfer endpoints: ``POST /store/orders/{id}/transfer/request``
and ``POST /store/orders/{id}/transfer/cancel``, plus the Phase 5
token-authorized ``POST /store/orders/{id}/transfer/accept`` and
``POST /store/orders/{id}/transfer/decline``.

Covers the HTTP surface of the transfer service (the service itself is
covered by ``ceto.tests.services.orders``): the exact ``StoreOrderResponse``
envelope all four routes answer, the publishable-key gate (an anonymous and
a customer-less session are ``401 unauthorized`` on the
customer-authenticated pair; the token-authorized pair is
guest-dispatchable like retrieval and refuses a missing or wrong key the
same way), the pinned bodies — the request validates
``StoreRequestOrderTransfer`` with unknown fields forbidden, cancel carries
none, accept/decline validate the strict ``{token}`` payloads — the
requester email derived from the session's User → Contact convention and
never from the payload, the masked service errors (unknown/wrong-scoped/
cancelled ``404 not_found``, an owned order or a missing pending request
``400 invalid_data``, a foreign cancel and every failing token ``403
not_allowed``) and the single-use token that never surfaces. Orders are
placed through the HTTP surface itself; every placed order is committed so
a later failing request's rollback cannot erase it.
"""

import json
import unittest
import uuid
from collections import Counter

import frappe
from frappe.utils import add_to_date, now_datetime
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.orders.transfer import (
	TRANSFER_ACCEPTED_HOOK,
	TRANSFER_DECLINED_HOOK,
	TRANSFER_REQUESTED_HOOK,
)
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.orders import StoreOrderResponse

#: Captured deliveries of the ``ceto_order_transfer_requested`` hook, so the
#: minted plaintext token can be proven absent from every response.
HOOK_CALLS: list[dict] = []

#: Captured deliveries of the completion hooks, so the consumed credential
#: can be proven absent from them and from every response.
ACCEPTED_CALLS: list[dict] = []
DECLINED_CALLS: list[dict] = []


def record_transfer(**kwargs) -> None:
	HOOK_CALLS.append(kwargs)


def record_accepted(**kwargs) -> None:
	ACCEPTED_CALLS.append(kwargs)


def record_declined(**kwargs) -> None:
	DECLINED_CALLS.append(kwargs)


def delivery_hook_path() -> str:
	return "ceto.tests.api.store.test_orders_transfers.record_transfer"


def accepted_hook_path() -> str:
	return "ceto.tests.api.store.test_orders_transfers.record_accepted"


def declined_hook_path() -> str:
	return "ceto.tests.api.store.test_orders_transfers.record_declined"


class TestOrderTransferAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# A committed earlier cart leaves its guest-linked temporary Address
		# behind; discarding keeps later fixtures addressless on purpose.
		self.masters.discard_committed_cart_temporaries()
		# Frappe throttles user creation per hour; most cases create their
		# own customer.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}
		HOOK_CALLS.clear()
		ACCEPTED_CALLS.clear()
		DECLINED_CALLS.clear()

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def test_the_session_customer_requests_the_exact_order_envelope(self) -> None:
		email, _customer = self._customer("envelope")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		# The envelope is exactly the pinned StoreOrderResponse: {order} —
		# no selector wrapper and never the minted token.
		self.assertEqual(set(body), {"order"})
		order = body["order"]
		self.assertEqual(order["id"], order_id)
		# The order itself is unchanged: the pending transfer writes no
		# lineage (Recorded Decision 12) and the guest order stays guest.
		self.assertEqual(order["email"], "guest@example.com")
		self.assertEqual(order["status"], "pending")
		self.assertIsNone(order["customer_id"])
		self.assertEqual(StoreOrderResponse.model_validate(body).model_dump(mode="json"), body)

		# The plaintext token reached exactly the delivery hook — order id
		# and the order's current email, never the API response.
		self.assertEqual(len(HOOK_CALLS), 1)
		self.assertEqual(HOOK_CALLS[0]["order_id"], order_id)
		self.assertEqual(HOOK_CALLS[0]["email"], "guest@example.com")
		self.assertNotIn(HOOK_CALLS[0]["token"], json.dumps(body))
		self.assertNotIn("token", json.dumps(body))

	def test_the_request_records_the_session_identity_and_the_pinned_body(self) -> None:
		email, customer = self._customer("recorded")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				response = self._dispatch(
					"POST",
					f"/ceto/store/orders/{order_id}/transfer/request",
					{"description": "It is mine", "update_order_email": True},
				)

		self.assertEqual(response.status_code, 200)
		pending = self._pending_transfer(order_id)
		self.assertIsNotNone(pending)
		# The requester identity is the session's Customer and the email the
		# session's User → Contact convention carries — the payload pinned
		# no recipient field to carry either.
		self.assertEqual(pending.requested_by, customer)
		self.assertEqual(pending.description, "It is mine")
		self.assertEqual(pending.original_email, "guest@example.com")
		self.assertEqual(pending.new_email, email)
		self.assertEqual(pending.status, "Pending")

	def test_the_requester_email_is_derived_never_payload(self) -> None:
		email, customer = self._customer("derived")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			# The body cannot nominate a recipient: the recipient-ish keys
			# are unknown fields and fail closed before anything is minted.
			refused = self._dispatch(
				"POST",
				f"/ceto/store/orders/{order_id}/transfer/request",
				{"email": "thief@example.com", "update_order_email": True},
			)
			self.assertEqual(refused.status_code, 400)
			self.assertEqual(refused.get_json()["type"], "invalid_data")
			self.assertIsNone(self._pending_transfer(order_id))

			accepted = self._dispatch(
				"POST", f"/ceto/store/orders/{order_id}/transfer/request", {"update_order_email": True}
			)
			self.assertEqual(accepted.status_code, 200)

		pending = self._pending_transfer(order_id)
		self.assertEqual(pending.requested_by, customer)
		self.assertEqual(pending.new_email, email)
		self.assertNotEqual(pending.new_email, "thief@example.com")

	def test_unknown_body_fields_fail_closed(self) -> None:
		email, _customer = self._customer("strict-body")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				for payload in (
					{"token": "tok_1"},
					{"customer_id": "cus_1"},
					{"email": "someone@example.com"},
					{"description": 42},
				):
					with self.subTest(payload=payload):
						response = self._dispatch(
							"POST", f"/ceto/store/orders/{order_id}/transfer/request", payload
						)
						self.assertEqual(response.status_code, 400)
						self.assertEqual(response.get_json()["type"], "invalid_data")
						self.assertNotIn("order", response.get_json())

		# Nothing was minted for any refused body: no pending record, no
		# delivery.
		self.assertIsNone(self._pending_transfer(order_id))
		self.assertEqual(HOOK_CALLS, [])

	def test_a_non_object_body_is_invalid_data(self) -> None:
		email, _customer = self._customer("array-body")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", ["nope"])

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_the_publishable_key_and_the_customer_session(self) -> None:
		# Customer-authenticated like upstream pins it: the route carries no
		# allow_guest (the router refuses a guest session before the
		# handler) and a signed-in user without exactly one linked Customer
		# is the same 401 (orders Recorded Decision 4). The key is checked
		# before the order is even looked up, so an unknown id suffices.
		unknown = f"order_{uuid.uuid4().hex}"
		with self.set_conf(ceto_cart=self.configuration):
			for path, payload in (
				(f"/ceto/store/orders/{unknown}/transfer/request", {}),
				(f"/ceto/store/orders/{unknown}/transfer/cancel", None),
			):
				with self.set_user("Guest"):
					for publishable_key in (None, "pk_unknown"):
						with self.subTest(path=path, publishable_key=publishable_key):
							response = self._dispatch("POST", path, payload, publishable_key=publishable_key)
							self.assertEqual(response.status_code, 401)
							self.assertEqual(response.get_json()["type"], "unauthorized")

				with self.set_create_user():
					response = self._dispatch("POST", path, payload)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_resolution_and_key_scope_mask_as_not_found(self) -> None:
		email, _customer = self._customer("masked")
		order_id = self._placed_order()
		unknown = f"order_{uuid.uuid4().hex}"
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			for path, payload in self._transfer_paths(order_id):
				# A mutating transfer surface refuses nothing about the key
				# beyond masking: a foreign order simply does not exist for
				# that key (Recorded Decision 5) — and a presented token
				# cannot unmask it into a credential error.
				response = self._dispatch("POST", path, payload, publishable_key="pk_other")
				self.assertEqual(response.status_code, 404)
				self.assertEqual(response.get_json(), {"type": "not_found", "message": "Order not found"})

			for path, payload in self._transfer_paths(unknown):
				unknown_response = self._dispatch("POST", path, payload)
				self.assertEqual(unknown_response.status_code, 404)
				self.assertEqual(
					unknown_response.get_json(), {"type": "not_found", "message": "Order not found"}
				)

			# A cancelled Sales Order is masked like an unknown id, on every
			# transfer surface (the failing dispatch's rollback undoes the
			# cancellation, so each dispatch re-applies it first).
			sales_order = frappe.db.get_value("Ceto Order Reference", order_id, "sales_order")
			for path, payload in self._transfer_paths(order_id):
				frappe.db.set_value("Sales Order", sales_order, "docstatus", 2, update_modified=False)
				response = self._dispatch("POST", path, payload)
				self.assertEqual(response.status_code, 404)
				self.assertEqual(response.get_json()["type"], "not_found")

	def test_an_owned_order_is_refused_as_invalid_data(self) -> None:
		# Guest-only eligibility (Recorded Decision 9): the requester's own
		# order is already owned and cannot be transferred.
		email, _customer = self._customer("owned")
		order_id = self._placed_order(email=email, claim=True)
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})

		self.assertEqual(response.status_code, 400)
		self.assertEqual(
			response.get_json(),
			{"type": "invalid_data", "message": "Only orders without an owner can be requested for transfer"},
		)
		self.assertIsNone(self._pending_transfer(order_id))

	def test_a_cancel_without_a_pending_request_is_invalid_data(self) -> None:
		email, _customer = self._customer("no-pending")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel")

		self.assertEqual(response.status_code, 400)
		self.assertEqual(
			response.get_json(),
			{"type": "invalid_data", "message": "No pending transfer request exists for this order"},
		)

	def test_only_the_requester_may_cancel(self) -> None:
		requester, requester_customer = self._customer("requester")
		stranger, _stranger_customer = self._customer("stranger")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user(requester):
				response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
			self.assertEqual(response.status_code, 200)
			# The failing cancel below rolls the open transaction back; the
			# pending record must survive it.
			frappe.db.commit()  # nosemgrep - the pending record must survive request rollbacks

			with self.set_user(stranger):
				response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel")

		self.assertEqual(response.status_code, 403)
		self.assertEqual(
			response.get_json(),
			{"type": "not_allowed", "message": "Only the customer who requested the transfer can cancel it"},
		)
		# The refused cancel consumed nothing.
		self.assertIsNotNone(self._pending_transfer(order_id))
		self.assertEqual(self._pending_transfer(order_id).requested_by, requester_customer)

	def test_the_requester_cancels_the_bodyless_request_once(self) -> None:
		requester, requester_customer = self._customer("cancelling")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(requester):
			requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
			self.assertEqual(requested.status_code, 200)

			# The pinned cancel carries no body at all.
			cancelled = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel")

		self.assertEqual(cancelled.status_code, 200)
		body = cancelled.get_json()
		self.assertEqual(set(body), {"order"})
		self.assertEqual(body["order"]["id"], order_id)
		self.assertEqual(StoreOrderResponse.model_validate(body).model_dump(mode="json"), body)
		# The record is gone, not flipped — and with it the digest-only
		# token; the replay below is a missing pending request.
		self.assertIsNone(self._pending_transfer(order_id))
		frappe.db.commit()  # nosemgrep - the deletion must survive the replay's rollback
		with self.set_conf(ceto_cart=self.configuration), self.set_user(requester):
			replayed = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel")

		self.assertEqual(replayed.status_code, 400)
		self.assertEqual(
			replayed.get_json(),
			{"type": "invalid_data", "message": "No pending transfer request exists for this order"},
		)
		self.assertEqual(frappe.db.count("Ceto Order Transfer", {"requested_by": requester_customer}), 0)

	def test_the_token_routes_are_guest_dispatchable(self) -> None:
		"""Upstream pins no customer authentication on accept/decline: the
		single-use token authorizes, so both routes are registered
		guest-dispatchable like retrieval — while the customer-authenticated
		request/cancel pair is not."""
		registered = {(route.method, route.path): route for route in ceto_router.routes}
		for path in ("/ceto/store/orders/{id}/transfer/accept", "/ceto/store/orders/{id}/transfer/decline"):
			with self.subTest(path=path):
				self.assertTrue(registered[("POST", path)].allow_guest)
		for path in ("/ceto/store/orders/{id}/transfer/request", "/ceto/store/orders/{id}/transfer/cancel"):
			with self.subTest(path=path):
				self.assertFalse(registered[("POST", path)].allow_guest)

	def test_the_transfer_token_accepts_the_exact_order_envelope(self) -> None:
		email, customer = self._customer("accepting")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
			# The commit below persists the pending record: the later
			# dispatches must not be able to roll the credential away.
			frappe.db.commit()  # nosemgrep - the pending credential must survive failure rollbacks
		token = HOOK_CALLS[0]["token"]
		# Guest dispatch: the token authorizes, no customer session exists.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [accepted_hook_path()]}):
				accepted = self._dispatch(
					"POST", f"/ceto/store/orders/{order_id}/transfer/accept", {"token": token}
				)

		self.assertEqual(accepted.status_code, 200)
		body = accepted.get_json()
		# The envelope is exactly the pinned StoreOrderResponse: {order} —
		# no selector wrapper and never the consumed token.
		self.assertEqual(set(body), {"order"})
		order = body["order"]
		self.assertEqual(order["id"], order_id)
		# Acceptance applied the transfer's stored requester through the
		# HTTP surface: the served owner is the requesting Customer, the
		# email untouched without ``update_order_email``.
		self.assertEqual(order["customer_id"], customer)
		self.assertEqual(order["email"], "guest@example.com")
		self.assertEqual(order["status"], "pending")
		self.assertEqual(StoreOrderResponse.model_validate(body).model_dump(mode="json"), body)
		# The completion hook fired without any token material, and the
		# response leaks neither the token nor the internal Sales Order.
		self.assertEqual(len(ACCEPTED_CALLS), 1)
		self.assertEqual(ACCEPTED_CALLS[0]["order_id"], order_id)
		self.assertNotIn("token", ACCEPTED_CALLS[0])
		rendered = json.dumps(body)
		self.assertNotIn("token", rendered)
		self.assertNotIn(token, rendered)
		self.assertNotIn(self._sales_order(order_id), rendered)
		self.assertNotIn("sales_order", rendered)
		# The credential is consumed, the record closed — not deleted.
		self.assertEqual(self._transfer_status(order_id), "Accepted")

	def test_the_accepted_order_serves_the_update_order_email_address(self) -> None:
		email, customer = self._customer("readdressed")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch(
					"POST",
					f"/ceto/store/orders/{order_id}/transfer/request",
					{"update_order_email": True},
				)
				self.assertEqual(requested.status_code, 200)
			frappe.db.commit()  # nosemgrep - the pending credential must survive failure rollbacks
		token = HOOK_CALLS[0]["token"]
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			accepted = self._dispatch(
				"POST", f"/ceto/store/orders/{order_id}/transfer/accept", {"token": token}
			)

		self.assertEqual(accepted.status_code, 200)
		order = accepted.get_json()["order"]
		# The accepted ``update_order_email`` moved ownership and recorded
		# the requesting customer's email on the served order.
		self.assertEqual(order["customer_id"], customer)
		self.assertEqual(order["email"], email)

	def test_the_transfer_token_declines_the_exact_order_envelope(self) -> None:
		email, _customer = self._customer("declining")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
			frappe.db.commit()  # nosemgrep - the pending credential must survive failure rollbacks
		token = HOOK_CALLS[0]["token"]
		# Guest dispatch: the token authorizes, no customer session exists.
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			with self.patch_hooks({TRANSFER_DECLINED_HOOK: [declined_hook_path()]}):
				declined = self._dispatch(
					"POST", f"/ceto/store/orders/{order_id}/transfer/decline", {"token": token}
				)

		self.assertEqual(declined.status_code, 200)
		body = declined.get_json()
		# The envelope is exactly the pinned StoreOrderResponse: {order} —
		# the unchanged order, never the refused token.
		self.assertEqual(set(body), {"order"})
		order = body["order"]
		self.assertEqual(order["id"], order_id)
		# The refusal wrote nothing but the record: the order stays
		# guest-owned and the recorded email untouched.
		self.assertIsNone(order["customer_id"])
		self.assertEqual(order["email"], "guest@example.com")
		self.assertEqual(StoreOrderResponse.model_validate(body).model_dump(mode="json"), body)
		rendered = json.dumps(body)
		self.assertNotIn("token", rendered)
		self.assertNotIn(token, rendered)
		# The completion hook fired with the safe payload, no token material.
		self.assertEqual(len(DECLINED_CALLS), 1)
		self.assertEqual(DECLINED_CALLS[0]["order_id"], order_id)
		self.assertNotIn("token", DECLINED_CALLS[0])
		self.assertEqual(self._transfer_status(order_id), "Declined")

	def test_accept_and_decline_require_the_publishable_key_alone(self) -> None:
		"""The token never replaces the key: a missing or wrong key is ``401
		unauthorized`` even with a well-formed ``{token}`` body — and since
		the routes are guest-dispatchable, the anonymous session fails on
		the key alone."""
		unknown = f"order_{uuid.uuid4().hex}"
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for path in (
				f"/ceto/store/orders/{unknown}/transfer/accept",
				f"/ceto/store/orders/{unknown}/transfer/decline",
			):
				for publishable_key in (None, "pk_unknown"):
					with self.subTest(path=path, publishable_key=publishable_key):
						response = self._dispatch(
							"POST", path, {"token": "tok"}, publishable_key=publishable_key
						)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_the_token_bodies_are_strict(self) -> None:
		"""The pinned ``{token}`` payloads forbid unknown fields, an absent,
		empty or non-string token and a non-object body — every refusal
		``400 invalid_data`` before anything is resolved or consumed, with
		no ``fields`` selector on the token routes either."""
		unknown = f"order_{uuid.uuid4().hex}"
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for path in (
				f"/ceto/store/orders/{unknown}/transfer/accept",
				f"/ceto/store/orders/{unknown}/transfer/decline",
			):
				for payload in (
					{},
					{"token": ""},
					{"token": "   "},
					{"token": 42},
					{"token": "tok_1", "customer_id": "cus_1"},
					{"token": "tok_1", "email": "thief@example.com"},
					["nope"],
					# A query selector is just an unknown field of the
					# strict body.
					{"token": "tok_1", "fields": "id"},
				):
					with self.subTest(path=path, payload=payload):
						response = self._dispatch("POST", path, payload)
						self.assertEqual(response.status_code, 400)
						self.assertEqual(response.get_json()["type"], "invalid_data")
						self.assertNotIn("order", response.get_json())

	def test_every_failing_credential_is_the_same_not_allowed(self) -> None:
		"""Wrong and replayed tokens are the same masked ``403 not_allowed``
		``Invalid token.`` through the HTTP surface — and none moves
		ownership or consumes the record."""
		email, customer = self._customer("credentials")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
			frappe.db.commit()  # nosemgrep - the pending credential must survive failure rollbacks
		token = HOOK_CALLS[0]["token"]
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for path in (
				f"/ceto/store/orders/{order_id}/transfer/accept",
				f"/ceto/store/orders/{order_id}/transfer/decline",
			):
				with self.subTest(path=path):
					wrong = self._dispatch("POST", path, {"token": "tok_wrong"})
					self.assertEqual(wrong.status_code, 403)
					self.assertEqual(wrong.get_json(), {"type": "not_allowed", "message": "Invalid token."})

			accepted = self._dispatch(
				"POST", f"/ceto/store/orders/{order_id}/transfer/accept", {"token": token}
			)
			self.assertEqual(accepted.status_code, 200)
		# The commit below persists the acceptance: the replay's rollback
		# must not undo the ownership the replays are measured against.
		frappe.db.commit()  # nosemgrep - the acceptance must survive the replay rollbacks
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			replayed_accept = self._dispatch(
				"POST", f"/ceto/store/orders/{order_id}/transfer/accept", {"token": token}
			)
			replayed_decline = self._dispatch(
				"POST", f"/ceto/store/orders/{order_id}/transfer/decline", {"token": token}
			)
		for response in (replayed_accept, replayed_decline):
			self.assertEqual(response.status_code, 403)
			self.assertEqual(response.get_json(), {"type": "not_allowed", "message": "Invalid token."})
		# The acceptance stands and the replays consumed nothing further.
		self.assertEqual(self._transfer_status(order_id), "Accepted")
		self.assertEqual(frappe.db.get_value("Ceto Order Reference", order_id, "owner_customer"), customer)

	def test_an_expired_token_is_the_same_invalid_token(self) -> None:
		"""A token past its window is indistinguishable from a wrong one —
		the same ``403 not_allowed`` on both token routes, consuming
		nothing."""
		email, _customer = self._customer("expired")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
			frappe.db.commit()  # nosemgrep - the pending credential must survive failure rollbacks
		name = self._pending_transfer(order_id).name
		# Committed, so the refusals' rollbacks cannot make the token live
		# again for the next dispatch.
		frappe.db.set_value(
			"Ceto Order Transfer",
			name,
			"expires_at",
			add_to_date(now_datetime(), days=-1),
			update_modified=False,
		)
		frappe.db.commit()  # nosemgrep - the expired window must survive failure rollbacks
		token = HOOK_CALLS[0]["token"]
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for path in (
				f"/ceto/store/orders/{order_id}/transfer/accept",
				f"/ceto/store/orders/{order_id}/transfer/decline",
			):
				with self.subTest(path=path):
					expired = self._dispatch("POST", path, {"token": token})
					self.assertEqual(expired.status_code, 403)
					self.assertEqual(expired.get_json(), {"type": "not_allowed", "message": "Invalid token."})
		# The expired record still stands — refusal consumed nothing.
		self.assertIsNotNone(self._pending_transfer(order_id))

	def test_a_cancelled_token_is_the_missing_pending_refusal(self) -> None:
		"""A cancelled request's token died with its record: accept and
		decline land on the ``400 invalid_data`` missing-pending refusal,
		never a distinguishable cancelled-credential error."""
		email, _customer = self._customer("cancelled")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
				cancelled = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel")
				self.assertEqual(cancelled.status_code, 200)
			frappe.db.commit()  # nosemgrep - the deletion must survive the replay's rollback
		self.assertIsNone(self._pending_transfer(order_id))
		token = HOOK_CALLS[0]["token"]
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for path in (
				f"/ceto/store/orders/{order_id}/transfer/accept",
				f"/ceto/store/orders/{order_id}/transfer/decline",
			):
				with self.subTest(path=path):
					response = self._dispatch("POST", path, {"token": token})
					self.assertEqual(response.status_code, 400)
					self.assertEqual(
						response.get_json(),
						{
							"type": "invalid_data",
							"message": "No pending transfer request exists for this order",
						},
					)

	def test_the_routes_have_no_fields_selector_and_leak_no_token(self) -> None:
		email, _customer = self._customer("selector")
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
				# The request route pins no selector: a ``fields`` parameter
				# is just an unknown field of its strict body.
				selected = self._dispatch(
					"POST", f"/ceto/store/orders/{order_id}/transfer/request?fields=id", {}
				)
				self.assertEqual(selected.status_code, 400)
				self.assertEqual(selected.get_json()["type"], "invalid_data")

				requested = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
				self.assertEqual(requested.status_code, 200)
				# The served order is the full unchanged serialization, never
				# a narrowed one and never a token carrier.
				order = requested.get_json()["order"]
				self.assertIn("status", order)
				self.assertIn("email", order)
				rendered = json.dumps(requested.get_json())
				self.assertNotIn("token", rendered)
				self.assertNotIn(HOOK_CALLS[0]["token"], rendered)

				# The cancel route reads no body and pins no selector: the
				# query parameter is ignored and the full order comes back.
				cancelled = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/cancel?fields=id")
				self.assertEqual(cancelled.status_code, 200)
				self.assertEqual(set(cancelled.get_json()), {"order"})
				self.assertIn("status", cancelled.get_json()["order"])

	def test_the_transfer_routes_are_registered_exactly_once(self) -> None:
		"""All six implemented routes are wired once each — no drift, no duplicates."""
		registered = Counter(
			(route.method, route.path) for route in ceto_router.routes if "/store/orders" in route.path
		)
		self.assertEqual(
			set(registered),
			{
				("GET", "/ceto/store/orders/{id}"),
				("GET", "/ceto/store/orders"),
				("POST", "/ceto/store/orders/{id}/transfer/request"),
				("POST", "/ceto/store/orders/{id}/transfer/accept"),
				("POST", "/ceto/store/orders/{id}/transfer/cancel"),
				("POST", "/ceto/store/orders/{id}/transfer/decline"),
			},
		)
		self.assertEqual(max(registered.values()), 1)
		self.assertEqual(sum(registered.values()), 6)

	def _customer(self, label: str) -> tuple[str, str]:
		"""A committed Website User linked to its own Customer through a Contact.

		Returns ``(email, customer)``. The commit persists the fixture so a
		later failing request's rollback cannot erase the session identity
		the dispatches below still need (the promotion API tests commit for
		the same reason).
		"""
		email, customer = make_customer_with_user(label)
		frappe.db.commit()  # nosemgrep - the session identity must survive request rollbacks
		return email, customer

	def _placed_order(self, *, email: str = "guest@example.com", claim: bool = False) -> str:
		"""Create, fill, optionally claim, and complete a cart over the HTTP surface.

		Returns the public ``order_…`` id. With ``claim`` the guest cart is
		claimed by the ``email`` customer first, so the placed order carries
		their owner snapshot. The placed order is committed: a later test
		request that expects an error would otherwise roll the open
		transaction — and the order — back, as a real failed request would.
		"""
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				created = self._dispatch("POST", "/ceto/store/carts?fields=id", {"email": email})
				self.assertEqual(created.status_code, 200)
				cart_id = created.get_json()["cart"]["id"]
				added = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/line-items?fields=id",
					{"variant_id": self.masters.item, "quantity": 1},
				)
				self.assertEqual(added.status_code, 200)
				addressed = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}?fields=id",
					{
						"shipping_address": {
							"address_1": "1 Transfer Way",
							"city": "Bangkok",
							"country_code": "th",
						}
					},
				)
				self.assertEqual(addressed.status_code, 200)
				shipped = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/shipping-methods?fields=id",
					{"option_id": self.masters.flat_rate_rule},
				)
				self.assertEqual(shipped.status_code, 200)
				if claim:
					with self.set_user(email):
						claimed = self._dispatch(
							"POST", f"/ceto/store/carts/{cart_id}/customer?fields=id", None
						)
					self.assertEqual(claimed.status_code, 200)
			# The commit below persists the cart's temporary Address; it must
			# not outlive this test as the shared guest Customer's default.
			self.addCleanup(self.masters.discard_committed_cart_temporaries)
			with self.set_user(email if claim else "Guest"):
				completed = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/complete", {})
			self.assertEqual(completed.status_code, 200)
			order_id = completed.get_json()["order"]["id"]
			frappe.db.commit()  # nosemgrep - the placed order must survive request rollbacks
		return order_id

	def _pending_transfer(self, order_id: str | None):
		name = frappe.db.get_value("Ceto Order Transfer", {"order_reference": order_id, "status": "Pending"})
		return frappe.get_doc("Ceto Order Transfer", name) if name else None

	def _transfer_status(self, order_id: str | None) -> str | None:
		name = frappe.db.get_value("Ceto Order Transfer", {"order_reference": order_id})
		return frappe.db.get_value("Ceto Order Transfer", name, "status") if name else None

	def _sales_order(self, order_id: str | None) -> str | None:
		return frappe.db.get_value("Ceto Order Reference", order_id, "sales_order")

	@staticmethod
	def _transfer_paths(order_id: str) -> list[tuple[str, dict | None]]:
		"""The four transfer surfaces of ``order_id`` with their pinned bodies.

		The token routes send a well-formed body even where only resolution
		is under test: validation precedes resolution, so only a syntactically
		valid body can reach the masked service errors.
		"""
		return [
			(f"/ceto/store/orders/{order_id}/transfer/request", {}),
			(f"/ceto/store/orders/{order_id}/transfer/accept", {"token": "tok"}),
			(f"/ceto/store/orders/{order_id}/transfer/cancel", None),
			(f"/ceto/store/orders/{order_id}/transfer/decline", {"token": "tok"}),
		]

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | list | None = None,
		*,
		publishable_key: str | None = "pk_test",
	):
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


if __name__ == "__main__":
	unittest.main()
