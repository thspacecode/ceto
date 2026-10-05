"""Phase 4 transfer endpoints: ``POST /store/orders/{id}/transfer/request``
and ``POST /store/orders/{id}/transfer/cancel``.

Covers the HTTP surface of the transfer service (the service itself is
covered by ``ceto.tests.services.orders``): the exact ``StoreOrderResponse``
envelope both routes answer, the publishable-key + customer-session gate
(an anonymous and a customer-less session are ``401 unauthorized``), the
pinned bodies — the request validates ``StoreRequestOrderTransfer`` with
unknown fields forbidden, cancel carries none — the requester email derived
from the session's User → Contact convention and never from the payload,
the masked service errors (unknown/wrong-scoped/cancelled ``404
not_found``, an owned order or a missing pending request ``400
invalid_data``, a foreign cancel ``403 not_allowed``) and the single-use
token that never surfaces. Orders are placed through the HTTP surface
itself; every placed order is committed so a later failing request's
rollback cannot erase it.
"""

import json
import unittest
import uuid
from collections import Counter

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.orders.transfer import TRANSFER_REQUESTED_HOOK
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.orders import StoreOrderResponse

#: Captured deliveries of the ``ceto_order_transfer_requested`` hook, so the
#: minted plaintext token can be proven absent from every response.
HOOK_CALLS: list[dict] = []


def record_transfer(**kwargs) -> None:
	HOOK_CALLS.append(kwargs)


def delivery_hook_path() -> str:
	return "ceto.tests.api.store.test_orders_transfers.record_transfer"


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
			for path in (
				f"/ceto/store/orders/{order_id}/transfer/request",
				f"/ceto/store/orders/{order_id}/transfer/cancel",
			):
				# A mutating transfer surface refuses nothing about the key
				# beyond masking: a foreign order simply does not exist for
				# that key (Recorded Decision 5).
				response = self._dispatch("POST", path, {}, publishable_key="pk_other")
				self.assertEqual(response.status_code, 404)
				self.assertEqual(response.get_json(), {"type": "not_found", "message": "Order not found"})

			for path in (
				f"/ceto/store/orders/{unknown}/transfer/request",
				f"/ceto/store/orders/{unknown}/transfer/cancel",
			):
				unknown_response = self._dispatch("POST", path, {})
				self.assertEqual(unknown_response.status_code, 404)
				self.assertEqual(
					unknown_response.get_json(), {"type": "not_found", "message": "Order not found"}
				)

			# A cancelled Sales Order is masked like an unknown id.
			reference = frappe.get_doc("Ceto Order Reference", order_id)
			frappe.db.set_value("Sales Order", reference.sales_order, "docstatus", 2, update_modified=False)
			response = self._dispatch("POST", f"/ceto/store/orders/{order_id}/transfer/request", {})
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
		"""The implemented four are wired once each — no drift, no duplicates."""
		registered = Counter(
			(route.method, route.path) for route in ceto_router.routes if "/store/orders" in route.path
		)
		self.assertEqual(
			set(registered),
			{
				("GET", "/ceto/store/orders/{id}"),
				("GET", "/ceto/store/orders"),
				("POST", "/ceto/store/orders/{id}/transfer/request"),
				("POST", "/ceto/store/orders/{id}/transfer/cancel"),
			},
		)
		self.assertEqual(max(registered.values()), 1)
		self.assertEqual(sum(registered.values()), 4)

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
