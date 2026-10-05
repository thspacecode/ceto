"""Phase 3 listing endpoint: ``GET /store/orders``.

Covers the HTTP surface of the listing service (the service itself is
covered by ``ceto.tests.services.orders``): the exact pinned
``{orders, count, offset, limit}`` envelope validated against
``StoreOrderListResponse``, the customer-authenticated refusal the
no-``allow_guest`` decorator produces, the publishable key that filters
the page instead of masking it, the raw ``id``/``status`` wire formats
(one comma-separated value or repeated parameters) and the pinned
pagination bounds failing closed as ``400 invalid_data``. Orders are
placed through the HTTP surface itself; every placed order is committed
so a later failing request's rollback cannot erase it.
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
from ceto.types.http.store.orders import StoreOrderListResponse

ORDER_ID = re.compile(r"^order_[0-9a-f]{32}$")


class TestOrderListAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# A committed earlier cart leaves its guest-linked temporary Address
		# behind; discarding keeps later fixtures addressless on purpose.
		self.masters.discard_committed_cart_temporaries()
		# Frappe throttles user creation per hour; every case creates its
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

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def test_lists_the_session_customer_orders_in_the_pinned_envelope(self) -> None:
		email, customer = make_customer_with_user("listing")
		placed = [self._placed_order(email=email, claim=True) for _ in range(2)]
		guest_order = self._placed_order()

		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			response = self._dispatch("GET", "/ceto/store/orders")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		# The envelope is exactly the pinned StoreOrderListResponse with its
		# mirrored pagination defaults.
		self.assertEqual(set(body), {"orders", "count", "offset", "limit"})
		self.assertEqual(body["count"], 2)
		self.assertEqual((body["offset"], body["limit"]), (0, 50))
		# Newest first (Recorded Decision 7); every served order is the
		# asking customer's own — the handler resolved the session, so no
		# request parameter chose the owner.
		self.assertEqual([order["id"] for order in body["orders"]], list(reversed(placed)))
		self.assertEqual({order["customer_id"] for order in body["orders"]}, {customer})
		# A guest order belongs to no list (Recorded Decision 4).
		self.assertNotIn(guest_order, [order["id"] for order in body["orders"]])
		# And the served body validates against the pinned response model.
		self.assertEqual(StoreOrderListResponse.model_validate(body).model_dump(mode="json"), body)

	def test_requires_a_configured_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for publishable_key in (None, "pk_unknown"):
				with self.subTest(publishable_key=publishable_key):
					response = self._dispatch("GET", "/ceto/store/orders", publishable_key=publishable_key)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_an_anonymous_session_and_a_customerless_user_are_refused(self) -> None:
		# Customer-authenticated like upstream pins it: the route carries no
		# allow_guest (the router refuses a guest session before the
		# handler), and a signed-in user without exactly one linked
		# Customer is the same 401 (orders Recorded Decision 4).
		with self.set_conf(ceto_cart=self.configuration):
			with self.set_user("Guest"):
				response = self._dispatch("GET", "/ceto/store/orders")
			self.assertEqual(response.status_code, 401)
			self.assertEqual(response.get_json()["type"], "unauthorized")

			with self.set_create_user() as email:
				response = self._dispatch("GET", "/ceto/store/orders")
			self.assertEqual(response.status_code, 401)
			self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_unknown_query_keys_fail_as_invalid_data(self) -> None:
		# The strict contract rejects everything outside the pinned filters
		# (Recorded Decision 8) — including a client-supplied customer_id,
		# which must never be honored as an owner selector.
		email, _customer = make_customer_with_user("strict")
		# The refused requests below each roll the open transaction back;
		# the fixture must survive them (the promotion API tests commit for
		# the same reason).
		frappe.db.commit()  # nosemgrep - the fixture must survive request rollbacks
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			for query in (
				"customer_id=cus_x",
				"$and[0][status]=pending",
				"$or[0][id]=order_x",
				"order=-created_at",
				"with_deleted=true",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/orders?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")
					self.assertNotIn("orders", response.get_json())

	def test_the_id_and_status_filters_accept_the_pinned_wire_formats(self) -> None:
		email, _customer = make_customer_with_user("filtered")
		first = self._placed_order(email=email, claim=True)
		second = self._placed_order(email=email, claim=True)

		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			single = self._dispatch("GET", f"/ceto/store/orders?id={first}")
			self.assertEqual(single.status_code, 200)
			self.assertEqual(single.get_json()["count"], 1)
			self.assertEqual([order["id"] for order in single.get_json()["orders"]], [first])

			# The SDK's ``qs`` serializations — one comma-separated value or
			# repeated parameters — are the same list filter.
			for query in (f"id={first},{second}", f"id={first}&id={second}"):
				with self.subTest(query=query):
					both = self._dispatch("GET", f"/ceto/store/orders?{query}")
					self.assertEqual(both.status_code, 200)
					self.assertEqual(both.get_json()["count"], 2)
					self.assertEqual(
						{order["id"] for order in both.get_json()["orders"]}, {first, second}
					)

			# Every placed order reports ``pending`` (Recorded Decision 6).
			pending = self._dispatch("GET", "/ceto/store/orders?status=pending")
			self.assertEqual(pending.get_json()["count"], 2)

			# A reported-status member matches; every other pinned union
			# member matches nothing — exactly as upstream, an empty page
			# and never an error (Recorded Decision 6).
			completed = self._dispatch("GET", "/ceto/store/orders?status=completed")
			self.assertEqual(completed.get_json(), {"orders": [], "count": 0, "offset": 0, "limit": 50})

			# The pinned union is enforced at the route: an unknown member —
			# alone or inside a list, comma-separated or repeated — is
			# invalid data, never a silently empty page.
			for query in (
				"status=shelved",
				"status=pending,shelved",
				"status=pending&status=shelved",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/orders?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_pagination_slices_the_page_inside_the_pinned_bounds(self) -> None:
		email, _customer = make_customer_with_user("paged")
		placed = [self._placed_order(email=email, claim=True) for _ in range(3)]

		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			first = self._dispatch("GET", "/ceto/store/orders?limit=2")
			self.assertEqual(first.status_code, 200)
			body = first.get_json()
			self.assertEqual(body["count"], 3)
			self.assertEqual([order["id"] for order in body["orders"]], [placed[2], placed[1]])
			self.assertEqual((body["offset"], body["limit"]), (0, 2))

			second = self._dispatch("GET", "/ceto/store/orders?limit=2&offset=2")
			body = second.get_json()
			self.assertEqual([order["id"] for order in body["orders"]], [placed[0]])
			self.assertEqual((body["offset"], body["limit"]), (2, 2))

			# The read-model page bound is a Ceto decision (upstream bounds
			# no page size): outside the bounds is invalid data, never a
			# silently clamped page.
			for query in ("limit=101", "limit=-1", "offset=-1"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/orders?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

			# The bound itself is a valid page.
			full = self._dispatch("GET", "/ceto/store/orders?limit=100")
			self.assertEqual(full.status_code, 200)
			self.assertEqual(full.get_json()["limit"], 100)

	def test_the_fields_selector_applies_to_every_page_order(self) -> None:
		email, _customer = make_customer_with_user("selected")
		self._placed_order(email=email, claim=True)
		self._placed_order(email=email, claim=True)

		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			narrowed = self._dispatch("GET", "/ceto/store/orders?fields=id,status")
			self.assertEqual(narrowed.status_code, 200)
			for order in narrowed.get_json()["orders"]:
				self.assertEqual(set(order), {"id", "status"})

			response = self._dispatch("GET", "/ceto/store/orders?fields=nonsense")
			self.assertEqual(response.status_code, 400)
			self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_a_wrong_scoped_key_filters_the_page_instead_of_masking_it(self) -> None:
		# A read-only list refuses nothing (Recorded Decision 5): a foreign
		# key sees an empty 200 page — the scope comparison the retrieve
		# path masks as 404, applied as a filter here.
		email, _customer = make_customer_with_user("scoped")
		order_id = self._placed_order(email=email, claim=True)

		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			other = self._dispatch("GET", "/ceto/store/orders", publishable_key="pk_other")
			self.assertEqual(other.status_code, 200)
			self.assertEqual(other.get_json(), {"orders": [], "count": 0, "offset": 0, "limit": 50})

			own = self._dispatch("GET", f"/ceto/store/orders?id={order_id}")
			self.assertEqual(own.get_json()["count"], 1)
			served = own.get_json()["orders"][0]
			self.assertEqual(served["id"], order_id)
			self.assertRegex(served["id"], ORDER_ID)

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
							"address_1": "1 Listing Way",
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
