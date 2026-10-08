"""Phase 6 completion endpoint: ``POST /store/carts/{id}/complete``.

Covers the HTTP surface of the completion service (the service orchestration
itself is covered by ``ceto.tests.services.carts.test_completion``): the
exact ``StoreCompleteCartResponse`` union body, the replay/idempotency, the
refusal union with a fix-and-retry flow, ownership masking, the
publishable-key guard (missing key, wrong scope with no mutation), the strict
payload, the ``fields`` selection on either union member and the atomicity
promise — an expected settle validation failure returns the pinned
``OrderPlacementError`` refusal union (a ``200`` member) with the placement
rolled back to the settle savepoint, while an unexpected fault still fails
as ``500 internal_error``; either way the cart is left open and completable.

Note: a failed request rolls back the currently uncommitted transaction
(same as a real failed HTTP request), so every test that expects an error
and asserts state afterwards commits its cart first.
"""

import json
import re
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.ceto.doctype.ceto_customer_reference.ceto_customer_reference import mint_customer_id
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite

ORDER_ID = re.compile(r"^order_[0-9a-f]{32}$")


class TestCartCompletionAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# A committed earlier cart leaves its guest-linked temporary Address
		# behind; discarding keeps the refusal cases addressless on purpose.
		self.masters.discard_committed_cart_temporaries()
		# Frappe throttles user creation per hour; the ownership test creates
		# two users per run.
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

	def _prepared_cart(
		self, *, email: str | None = "guest@example.com", items: int = 1, user: str = "Guest"
	) -> str:
		"""Create a checkout-ready cart for ``user`` and commit it.

		Email/address/shipping can be missing (``email=None``, ``items=0``)
		to produce a cart the completion must refuse. A cart created for an
		authenticated user is owned by them and masked from everyone else.
		"""
		with self.set_conf(ceto_cart=self.configuration), self.set_user(user):
			created = self._dispatch("POST", "/ceto/store/carts?fields=id", {"email": email})
			self.assertEqual(created.status_code, 200)
			cart_id = created.get_json()["cart"]["id"]
			for _ in range(items):
				added = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}/line-items?fields=id",
					{"variant_id": self.masters.item, "quantity": 1},
				)
				self.assertEqual(added.status_code, 200)
			if items:
				addressed = self._dispatch(
					"POST",
					f"/ceto/store/carts/{cart_id}?fields=id",
					{
						"shipping_address": {
							"address_1": "1 Completion Way",
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
			# The commit below persists the cart's temporary Address; it must
			# not outlive this test as the shared guest Customer's default.
			self.addCleanup(self.masters.discard_committed_cart_temporaries)
			frappe.db.commit()  # nosemgrep - the cart must survive request rollbacks
		return cart_id

	def _complete(self, cart_id: str, payload: dict | None = None, *, query: str = "", **kwargs):
		return self._dispatch("POST", f"/ceto/store/carts/{cart_id}/complete{query}", payload or {}, **kwargs)

	def _order_reference(self, cart_id: str):
		name = frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name")
		return frappe.get_doc("Ceto Order Reference", name) if name else None

	def _quotation_of(self, cart_id: str) -> str:
		return frappe.db.get_value("Ceto Cart Reference", cart_id, "quotation")

	def test_guest_completes_the_cart_into_the_exact_order_union(self) -> None:
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			# The cart carries a locale: a cart-only column that must never
			# leak onto the placed order (the pinned StoreOrder has none).
			localized = self._dispatch("POST", f"/ceto/store/carts/{cart_id}", {"locale": "th-TH"})
			self.assertEqual(localized.status_code, 200)

			response = self._complete(cart_id)

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"type", "order"})
		self.assertEqual(body["type"], "order")
		order = body["order"]
		self.assertRegex(order["id"], ORDER_ID)
		self.assertEqual(order["email"], "guest@example.com")
		# A guest owns no contract-safe customer identity: the embedded
		# customer serializes as null.
		self.assertIsNone(order["customer"])
		self.assertNotIn("locale", order)
		self.assertEqual(len(order["items"]), 1)
		self.assertEqual(order["status"], "pending")

		# The placed order is booked as the cart's Ceto Order Reference, the
		# Quotation is submitted and the Sales Order stands behind it.
		reference = self._order_reference(cart_id)
		self.assertEqual(reference.name, order["id"])
		self.assertEqual(frappe.db.get_value("Quotation", self._quotation_of(cart_id), "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Sales Order", reference.sales_order, "docstatus"), 1)

	def test_replay_returns_the_same_order_and_the_cart_stays_masked(self) -> None:
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			first = self._complete(cart_id)
			self.assertEqual(first.status_code, 200)
			# Commit the placed order: every later error response would
			# otherwise roll the completion back (as a real failed request
			# would roll back the uncommitted transaction of its worker).
			frappe.db.commit()  # nosemgrep - simulate the preceding successful requests

			# The completed cart is masked on the whole cart surface.
			retrieved = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id")
			mutated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": self.masters.item, "quantity": 1},
			)

			# ...and every repeat replays the placed order, not a new one.
			second = self._complete(cart_id)

		self.assertEqual(retrieved.status_code, 404)
		self.assertEqual(retrieved.get_json()["type"], "not_found")
		self.assertEqual(mutated.status_code, 404)
		self.assertEqual(second.status_code, 200)
		self.assertEqual(second.get_json()["type"], "order")
		self.assertEqual(second.get_json()["order"]["id"], first.get_json()["order"]["id"])
		self.assertEqual(frappe.db.count("Ceto Order Reference", {"cart_id": cart_id}), 1)

	def test_a_claimed_order_embeds_the_owner_customer_and_replays_it(self) -> None:
		email, customer = make_customer_with_user("api-order-customer")
		reference = frappe.get_doc(
			{
				"doctype": "Ceto Customer Reference",
				"customer_id": mint_customer_id(),
				"customer": customer,
				"user": email,
			}
		).insert(ignore_permissions=True)
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			claimed = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/customer")
			self.assertEqual(claimed.status_code, 200)

			completed = self._complete(cart_id)

		self.assertEqual(completed.status_code, 200)
		order = completed.get_json()["order"]
		# The embedded customer is the customers contract's pinned identity:
		# the stable cus_… id behind the claiming session's identity chain.
		self.assertEqual(order["customer"]["id"], reference.name)
		self.assertEqual(order["customer"]["email"], email)
		# The recorded compatibility deviation: customer_id keeps the ERPNext
		# Customer name the carts surface has always reported, deliberately
		# beside the embedded cus_… id.
		self.assertEqual(order["customer_id"], customer)
		self.assertNotEqual(order["customer_id"], order["customer"]["id"])

		# The replay re-serializes the same embedded customer.
		with self.set_conf(ceto_cart=self.configuration), self.set_user(email):
			replayed = self._complete(cart_id)
		self.assertEqual(replayed.status_code, 200)
		self.assertEqual(replayed.get_json()["order"]["customer"], order["customer"])
		self.assertEqual(frappe.db.count("Ceto Order Reference", {"cart_id": cart_id}), 1)

	def test_completed_fixture_leaves_no_address_for_addressless_carts(self) -> None:
		# Regression: a placed order is committed (the replay guarantee needs
		# it to survive request rollbacks), and the commit persists the cart's
		# temporary Address — now also linked from the committed Sales Order
		# the mapper copied it onto. A leftover Address is the guest party's
		# only Shipping address, so ERPNext refills the empty slot of the next
		# addressless cart from it (party.get_party_shipping_address) and that
		# cart silently inherits this fixture's Thailand address. The fixture
		# cleanup under test must detach the Sales Order slots and leave no
		# guest-linked temporary behind, and the next addressless cart must
		# stay addressless and still be able to apply the country rule.
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			completed = self._complete(cart_id)
			self.assertEqual(completed.status_code, 200)
			sales_order = self._order_reference(cart_id).sales_order
			address = frappe.db.get_value("Sales Order", sales_order, "shipping_address_name")
			self.assertTrue(address)

			frappe.db.commit()  # nosemgrep - recreate the committed completed fixture
			self.masters.discard_committed_cart_temporaries()
			self.assertFalse(
				frappe.get_all(
					"Address",
					filters=[
						["Dynamic Link", "link_doctype", "=", "Customer"],
						["link_name", "=", self.masters.customer],
						["address_title", "like", "Cart %"],
					],
				)
			)

			# The next addressless cart with a line stays addressless...
			created = self._dispatch("POST", "/ceto/store/carts?fields=id", {})
			self.assertEqual(created.status_code, 200)
			fresh = created.get_json()["cart"]["id"]
			added = self._dispatch(
				"POST",
				f"/ceto/store/carts/{fresh}/line-items?fields=id",
				{"variant_id": self.masters.item, "quantity": 1},
			)
			self.assertEqual(added.status_code, 200)
			self.assertIsNone(self._quotation_address(fresh))
			# ...and can still apply the country rule.
			applied = self._dispatch(
				"POST",
				f"/ceto/store/carts/{fresh}/shipping-methods?fields=id,shipping_methods",
				{"option_id": self.masters.country_rate_rule},
			)
			self.assertEqual(applied.status_code, 200)
			self.assertEqual(
				applied.get_json()["cart"]["shipping_methods"][0]["shipping_option_id"],
				self.masters.country_rate_rule,
			)

	def _quotation_address(self, cart_id: str) -> str | None:
		return frappe.db.get_value("Quotation", self._quotation_of(cart_id), "shipping_address_name")

	def test_incomplete_carts_refuse_with_the_pinned_error_union(self) -> None:
		for email, items, refusal in (
			# An empty cart cannot be placed.
			("guest@example.com", 0, "EmptyCartError"),
			# A cart without an email has not checked out far enough.
			(None, 1, "MissingCartEmailError"),
		):
			with self.subTest(refusal=refusal):
				cart_id = self._prepared_cart(email=email, items=items)
				with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
					response = self._complete(cart_id)

				self.assertEqual(response.status_code, 200)
				body = response.get_json()
				self.assertEqual(set(body), {"type", "cart", "error"})
				self.assertEqual(body["type"], "cart")
				self.assertEqual(set(body["error"]), {"message", "name", "type"})
				self.assertEqual(body["error"]["name"], refusal)
				self.assertEqual(body["error"]["type"], "incomplete_cart")
				self.assertEqual(body["cart"]["id"], cart_id)
				self.assertIsNone(self._order_reference(cart_id))

	def test_refused_cart_stays_open_and_a_fix_and_retry_places_the_order(self) -> None:
		# A cart with a line but no email is refused; the client fixes the
		# cart and retries — the refusal must have left it exactly as it was.
		cart_id = self._prepared_cart(email=None, items=1)
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			refused = self._complete(cart_id)
			self.assertEqual(refused.status_code, 200)
			self.assertEqual(refused.get_json()["type"], "cart")

			before = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,email,total")
			self.assertEqual(before.status_code, 200)
			self.assertIsNone(before.get_json()["cart"]["email"])

			updated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}?fields=id",
				{"email": "guest@example.com"},
			)
			self.assertEqual(updated.status_code, 200)

			completed = self._complete(cart_id)

		self.assertEqual(completed.status_code, 200)
		self.assertEqual(completed.get_json()["type"], "order")
		self.assertEqual(completed.get_json()["order"]["email"], "guest@example.com")

	def test_competing_customer_is_masked_as_not_found(self) -> None:
		owner_email, _owner = make_customer_with_user("owner")
		other_email, _other = make_customer_with_user("other")
		with self.set_conf(ceto_cart=self.configuration):
			# The cart is created (and so owned) by the first customer.
			cart_id = self._prepared_cart(user=owner_email)
			with self.set_user(other_email):
				response = self._complete(cart_id)

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json()["type"], "not_found")
		self.assertIsNone(self._order_reference(cart_id))

	def test_requires_a_publishable_key(self) -> None:
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._complete(cart_id, publishable_key=None)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_wrong_scoped_key_causes_no_mutation(self) -> None:
		# The scope check runs inside the cart row lock before anything is
		# written, so a rejecting key leaves the cart unchanged — and still
		# completable with the correctly scoped key.
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			before = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,total")
			response = self._complete(cart_id, publishable_key="pk_other")
			after = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,total")

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.get_json()["type"], "not_allowed")
		self.assertIsNone(self._order_reference(cart_id))
		self.assertEqual(after.get_json()["cart"], before.get_json()["cart"])

		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			completed = self._complete(cart_id)
		self.assertEqual(completed.status_code, 200)
		self.assertEqual(completed.get_json()["type"], "order")

	def test_rejects_payloads_that_are_not_the_pinned_strict_object(self) -> None:
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for payload in (
				{"unknown": True},
				{"idempotency_key": "idem-1", "payment": {"provider": "x"}},
				{"idempotency_key": 5},
			):
				with self.subTest(payload=payload):
					response = self._complete(cart_id, payload)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")
					self.assertIsNone(self._order_reference(cart_id))

			# The valid pinned body (only the optional idempotency key) goes
			# through and is forwarded to the payment readiness hooks.
			completed = self._complete(cart_id, {"idempotency_key": "idem-1"})

		self.assertEqual(completed.status_code, 200)
		self.assertEqual(completed.get_json()["type"], "order")

	def test_fields_select_whichever_union_member_is_returned(self) -> None:
		open_cart = self._prepared_cart(email=None, items=1)
		placed_cart = self._prepared_cart()
		fields_cart = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			refused = self._complete(open_cart, query="?fields=id,total")
			completed = self._complete(placed_cart, query="?fields=id,total")
			unknown = self._complete(fields_cart, query="?fields=nonsense")

		refused_body = refused.get_json()
		self.assertEqual(set(refused_body), {"type", "cart", "error"})
		self.assertEqual(refused_body["type"], "cart")
		self.assertEqual(set(refused_body["cart"]), {"id", "total"})

		completed_body = completed.get_json()
		self.assertEqual(set(completed_body), {"type", "order"})
		self.assertEqual(set(completed_body["order"]), {"id", "total"})

		self.assertEqual(unknown.status_code, 400)
		self.assertEqual(unknown.get_json()["type"], "invalid_data")

	def test_conversion_failure_rolls_back_and_the_cart_stays_completable(self) -> None:
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			with patch(
				"ceto.services.carts.completion.convert_quotation_to_sales_order",
				side_effect=RuntimeError("boom"),
			):
				response = self._complete(cart_id)

			self.assertEqual(response.status_code, 500)
			self.assertEqual(response.get_json()["type"], "internal_error")
			# Nothing of the settle survived: draft Quotation, no order
			# reference, and the cart is still open on the cart surface.
			self.assertIsNone(self._order_reference(cart_id))
			quotation = frappe.db.get_value("Ceto Cart Reference", cart_id, "quotation")
			self.assertEqual(frappe.db.get_value("Quotation", quotation, "docstatus"), 0)
			cart = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,total")
			self.assertEqual(cart.status_code, 200)

			# The very same request succeeds on the retry.
			completed = self._complete(cart_id)

		self.assertEqual(completed.status_code, 200)
		self.assertEqual(completed.get_json()["type"], "order")

	def test_credit_failure_rolls_back_the_order_and_the_ledger(self) -> None:
		code = f"GC-API-DONE-{self.masters.suffix}"
		wallet = self.masters.make_gift_card(code, credit_total=10.0)
		frappe.db.commit()  # nosemgrep - the wallet must survive request rollbacks
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			applied = self._dispatch(
				"POST", f"/ceto/store/carts/{cart_id}/gift-cards?fields=id,credit_lines", {"code": code}
			)
			self.assertEqual(applied.status_code, 200)
			frappe.db.commit()  # nosemgrep - commit the applied hold with the cart
			reservation = frappe.db.get_value(
				"Ceto Cart Credit Reservation",
				{"quotation": frappe.db.get_value("Ceto Cart Reference", cart_id, "quotation")},
				"name",
			)

			with patch(
				"ceto.services.carts.completion.CartCredits.consume_cart_credits",
				side_effect=RuntimeError("boom"),
			):
				response = self._complete(cart_id)

			self.assertEqual(response.status_code, 500)
			self.assertEqual(response.get_json()["type"], "internal_error")
			# The whole completion rolled back: no order, draft Quotation, the
			# hold is still an open reservation and the wallet is untouched.
			self.assertIsNone(self._order_reference(cart_id))
			quotation = frappe.db.get_value("Ceto Cart Reference", cart_id, "quotation")
			self.assertEqual(frappe.db.get_value("Quotation", quotation, "docstatus"), 0)
			self.assertEqual(
				frappe.db.get_value("Ceto Cart Credit Reservation", reservation, "status"), "Reserved"
			)
			ledger = frappe.db.get_value(
				"Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True
			)
			self.assertAlmostEqual(flt(ledger.debit_total), 0)
			self.assertAlmostEqual(flt(ledger.balance), 10.0)

			# The retry settles everything: order placed, hold consumed, the
			# wallet debited exactly once.
			completed = self._complete(cart_id)

		self.assertEqual(completed.status_code, 200)
		order = completed.get_json()["order"]
		self.assertEqual(order["gift_card_total"], 10.0)
		ledger = frappe.db.get_value("Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True)
		self.assertAlmostEqual(flt(ledger.debit_total), 10.0)
		self.assertAlmostEqual(flt(ledger.balance), 0)
		self.assertEqual(
			frappe.db.get_value("Ceto Cart Credit Reservation", reservation, "status"), "Consumed"
		)

	def test_a_settle_validation_failure_returns_the_pinned_refusal_union(self) -> None:
		# An expected Frappe/ERPNext validation failure while placing is a
		# 200 refusal union member — not a 500 — with the whole placement
		# rolled back to the settle savepoint and the cart retry-ready.
		cart_id = self._prepared_cart()
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			with patch(
				"ceto.services.carts.completion.convert_quotation_to_sales_order",
				side_effect=frappe.ValidationError("Credit limit exceeded for customer"),
			):
				response = self._complete(cart_id)

			self.assertEqual(response.status_code, 200)
			body = response.get_json()
			self.assertEqual(set(body), {"type", "cart", "error"})
			self.assertEqual(body["type"], "cart")
			self.assertEqual(body["error"]["name"], "OrderPlacementError")
			self.assertEqual(body["error"]["type"], "order_placement_error")
			self.assertEqual(body["cart"]["id"], cart_id)
			self.assertIsNone(self._order_reference(cart_id))
			self.assertEqual(frappe.db.get_value("Quotation", self._quotation_of(cart_id), "docstatus"), 0)

			# The retry (a programming fault would 500 instead — see the
			# RuntimeError tests below) places the order: HTTP 200 both ways.
			completed = self._complete(cart_id)

		self.assertEqual(completed.status_code, 200)
		self.assertEqual(completed.get_json()["type"], "order")

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
