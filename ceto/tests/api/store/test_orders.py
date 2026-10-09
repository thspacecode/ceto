"""Phase 2 retrieval endpoint: ``GET /store/orders/{id}``.

Covers the HTTP surface of the retrieval service (the service itself is
covered by ``ceto.tests.services.orders``): the exact ``StoreOrderResponse``
envelope, the publishable-key requirement, wrong-scope/unknown/broken
masking as the same ``404 not_found`` (orders Recorded Decision 5), the
capability-based guest access (Recorded Decision 4), the ``fields``
selector and the Sales Order identity that must never surface. Orders are
placed through the HTTP surface itself; every placed order is committed so
a later failing request's rollback cannot erase it.
"""

import json
import re
import unittest
import uuid

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.orders import StoreOrderResponse

ORDER_ID = re.compile(r"^order_[0-9a-f]{32}$")


class TestOrderRetrieveAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# A committed earlier cart leaves its guest-linked temporary Address
		# behind; discarding keeps later fixtures addressless on purpose.
		self.masters.discard_committed_cart_temporaries()
		# Frappe throttles user creation per hour; the capability test
		# creates two users per run.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {
				"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"},
				"pk_other": {"region_id": "reg_other", "sales_channel_id": "sc_other"},
			},
		}

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def test_guest_retrieves_the_exact_order_envelope(self) -> None:
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", f"/ceto/store/orders/{order_id}")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		# The envelope is exactly the pinned StoreOrderResponse: {order}.
		self.assertEqual(set(body), {"order"})
		order = body["order"]
		self.assertRegex(order["id"], ORDER_ID)
		self.assertEqual(order["id"], order_id)
		self.assertEqual(order["email"], "guest@example.com")
		self.assertEqual(order["status"], "pending")
		self.assertEqual(order["payment_status"], "not_paid")
		self.assertEqual(order["fulfillment_status"], "not_fulfilled")
		self.assertIsNone(order["customer_id"])
		self.assertEqual(order["region_id"], "reg_test")
		self.assertEqual(order["sales_channel_id"], "sc_test")
		self.assertEqual(len(order["items"]), 1)
		# And the served body validates against the pinned response model.
		self.assertEqual(StoreOrderResponse.model_validate(body).model_dump(mode="json"), body)

	def test_the_sales_order_identity_never_surfaces(self) -> None:
		order_id = self._placed_order()
		reference = frappe.get_doc("Ceto Order Reference", order_id)

		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", f"/ceto/store/orders/{order_id}")

		rendered = json.dumps(response.get_json())
		# The public id is the order's identity; the ERPNext Sales Order's
		# name and the lineage's Quotation name appear nowhere.
		self.assertEqual(reference.name, order_id)
		self.assertNotIn(reference.sales_order, rendered)
		self.assertNotIn(frappe.db.get_value("Ceto Cart Reference", reference.cart_id, "quotation"), rendered)
		self.assertNotIn("sales_order", rendered)

	def test_requires_a_configured_publishable_key(self) -> None:
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for publishable_key in (None, "pk_unknown"):
				with self.subTest(publishable_key=publishable_key):
					response = self._dispatch(
						"GET", f"/ceto/store/orders/{order_id}", publishable_key=publishable_key
					)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_a_wrong_scoped_key_is_masked_as_not_found(self) -> None:
		# A read-only surface refuses nothing: a foreign order simply does
		# not exist for that key (Recorded Decision 5) — not_found, never
		# the not_allowed the mutating cart routes answer with.
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", f"/ceto/store/orders/{order_id}", publishable_key="pk_other")

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json(), {"type": "not_found", "message": "Order not found"})

	def test_an_unknown_order_is_masked_as_not_found(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", f"/ceto/store/orders/order_{uuid.uuid4().hex}")

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json()["type"], "not_found")
		self.assertNotIn("order", response.get_json())

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		# State broken after the fact is masked like an unknown id — never a
		# 500. The service re-checks the lineage on every retrieval; the
		# service suite covers the other breakage modes.
		order_id = self._placed_order()
		reference = frappe.get_doc("Ceto Order Reference", order_id)
		quotation = frappe.db.get_value("Ceto Cart Reference", reference.cart_id, "quotation")
		frappe.db.set_value("Quotation", quotation, "docstatus", 2, update_modified=False)

		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("GET", f"/ceto/store/orders/{order_id}")

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json()["type"], "not_found")

	def test_retrieval_is_capability_based_not_ownership_gated(self) -> None:
		# The unguessable id is the credential (Recorded Decision 4): the
		# owner, a guest session and a different customer all resolve the
		# same order — no customer gate beyond the key.
		email, customer = make_customer_with_user("owner")
		other, _other_customer = make_customer_with_user("other")
		order_id = self._placed_order(email=email, claim=True)

		for user in (email, "Guest", other):
			with self.set_conf(ceto_cart=self.configuration), self.set_user(user):
				response = self._dispatch("GET", f"/ceto/store/orders/{order_id}?fields=id,customer_id")
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_json()["order"], {"id": order_id, "customer_id": customer})

	def test_the_fields_selector_narrows_extends_and_fails_closed(self) -> None:
		order_id = self._placed_order()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			full = self._dispatch("GET", f"/ceto/store/orders/{order_id}").get_json()["order"]

			narrowed = self._dispatch("GET", f"/ceto/store/orders/{order_id}?fields=id,status,total")
			self.assertEqual(narrowed.status_code, 200)
			self.assertEqual(set(narrowed.get_json()["order"]), {"id", "status", "total"})
			self.assertEqual(narrowed.get_json()["order"]["total"], full["total"])

			extended = self._dispatch("GET", f"/ceto/store/orders/{order_id}?fields=id,+total")
			self.assertEqual(extended.status_code, 200)
			self.assertEqual(set(extended.get_json()["order"]), {"id", "total"})

			trimmed = self._dispatch("GET", f"/ceto/store/orders/{order_id}?fields=-items,-metadata")
			self.assertEqual(trimmed.status_code, 200)
			trimmed_order = trimmed.get_json()["order"]
			self.assertNotIn("items", trimmed_order)
			self.assertNotIn("metadata", trimmed_order)
			self.assertEqual(set(trimmed_order) | {"items", "metadata"}, set(full))

			# Unknown fields fail closed as 400 invalid_data — including the
			# internal identity, which is not a selectable field either.
			for fields in ("nonsense", "sales_order"):
				with self.subTest(fields=fields):
					response = self._dispatch("GET", f"/ceto/store/orders/{order_id}?fields={fields}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")
					self.assertNotIn("order", response.get_json())

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
							"address_1": "1 Retrieval Way",
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

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
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
