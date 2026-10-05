"""Order-transfer ownership visibility: the retrieve/list matrix acceptance moves.

The regression proof of the accept surface's customer-visible consequence
(orders Recorded Decisions 2, 4 and 9): a placed guest order belongs to
nobody — the unguessable ``order_…`` id is its only credential — so before
acceptance it answers retrieve by capability alone with ``customer_id:
null`` and appears in **no** customer's list, and acceptance moves that
visibility exactly once, to the transfer's recorded requester. One real
transfer is proven through both read surfaces:

- **retrieve** stays capability-based across the ownership move: the id
  answers before and after acceptance — serving the recorded requester
  once the transfer is consumed — no customer gate grows on it, and the
  masked ``404 not_found`` family (unknown id, wrong-scoped key) is
  unchanged by the ownership write (Recorded Decision 5).
- **list** is strictly owner-scoped: before acceptance the guest order is
  absent from every customer's page; after acceptance exactly the recorded
  requester's page contains it — served byte-identical to its retrieval
  and addressable by its public id — while every other customer, including
  the guest party the Sales Order names, still cannot see it, not even by
  its exact id.

The fixture books a real guest order through the completion shape (guest
cart → submitted Quotation → submitted Sales Order), mints the pending
transfer through the real request service and accepts it with the token
the delivery hook received, on the test site inside a single rolled-back
transaction.
"""

import json
import uuid

import frappe

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.service import OrderService
from ceto.services.orders.transfer import TRANSFER_REQUESTED_HOOK
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCartAddressPayload,
	StoreCompleteCart,
	StoreCreateCart,
	StoreUpdateCart,
)

ORDER_EMAIL = "guest@example.com"

#: Captured deliveries of the ``ceto_order_transfer_requested`` hook.
REQUEST_HOOK_CALLS: list[dict] = []


def record_requested(**kwargs) -> None:
	REQUEST_HOOK_CALLS.append(kwargs)


def requested_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_visibility.record_requested"


class TestOrderTransferVisibility(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.foreign_key = CartPublishableKey(region_id="reg_other", sales_channel_id="sc_other")
		# Frappe throttles user creation per hour; the visibility matrix
		# creates one user per run.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		# The adapter would resolve both callers from their sessions; the
		# recorded requester is the only one acceptance ever serves.
		self.requester_email, self.requester = make_customer_with_user("visibility")
		self.other_email, self.other = make_customer_with_user("bystander")
		self.order = self._make_order_reference()
		REQUEST_HOOK_CALLS.clear()

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _make_order_reference(self):
		"""Place a real guest order through the completion flow.

		The completion books the order reference with its submitted
		Quotation and Sales Order, and the order stays guest-owned —
		exactly the order a transfer recovers.
		"""
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.carts.create(StoreCreateCart(email=ORDER_EMAIL))
			self.carts.add_line_item(
				reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.item, quantity=1)
			)
			self.carts.update(
				reference.cart_id,
				StoreUpdateCart(
					shipping_address=StoreCartAddressPayload(
						address_1="1 Visibility Way", city="Bangkok", country_code="th"
					)
				),
			)
			self.carts.set_shipping_method(
				reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)
			self.completion.complete(reference.cart_id, StoreCompleteCart())
		return frappe.get_doc(
			"Ceto Order Reference",
			frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"),
		)

	def _request(self) -> str:
		"""Mint the pending transfer through the real request service; return the token."""
		with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [requested_hook_path()]}):
			self.orders.request_transfer(
				self.order.order_id,
				self.key,
				requested_by=self.requester,
				requester_email=self.requester_email,
			)
		return REQUEST_HOOK_CALLS[-1]["token"]

	def test_acceptance_moves_list_visibility_to_the_recorded_requester(self) -> None:
		# Before acceptance the guest order belongs to nobody: the
		# capability id answers with no owner, and no customer's list
		# carries it — neither the future requester's, nor another
		# customer's, nor the guest party the Sales Order names.
		guest = self.orders.retrieve(self.order.order_id, self.key)
		self.assertIsNone(guest["customer_id"])
		for customer in (self.requester, self.other, self.masters.customer):
			page = self.orders.list(customer, self.key)
			self.assertEqual(page["count"], 0)
			self.assertEqual(page["orders"], [])

		# The masked surface is already in place before the ownership moves.
		with self.assertRaises(RouteNotFoundError) as raised:
			self.orders.retrieve(self.order.order_id, self.foreign_key)
		self.assertEqual(raised.exception.status_code, 404)

		self.orders.accept_transfer(self.order.order_id, self.key, token=self._request())

		# Retrieve itself grows no customer gate (Recorded Decision 4): the
		# capability id alone still answers after the move — now serving
		# the recorded requester as the order's owner.
		retrieved = self.orders.retrieve(self.order.order_id, self.key)
		self.assertEqual(retrieved["id"], self.order.order_id)
		self.assertEqual(retrieved["customer_id"], self.requester)

		# The recorded requester sees the order in the list, served
		# byte-identical to its retrieval and addressable by its public id.
		mine = self.orders.list(self.requester, self.key)
		self.assertEqual(mine["count"], 1)
		self.assertEqual([order["id"] for order in mine["orders"]], [self.order.order_id])
		self.assertEqual(mine["orders"][0]["customer_id"], self.requester)
		self.assertEqual(
			json.dumps(mine["orders"][0], sort_keys=True),
			json.dumps(retrieved, sort_keys=True),
		)
		self.assertEqual(self.orders.list(self.requester, self.key, ids=self.order.order_id)["count"], 1)

		# Every other customer still cannot see it: the order is absent
		# from their page, and not even its exact public id lists it.
		for customer in (self.other, self.masters.customer):
			page = self.orders.list(customer, self.key)
			self.assertEqual(page["count"], 0)
			self.assertEqual(page["orders"], [])
			by_id = self.orders.list(customer, self.key, ids=self.order.order_id)
			self.assertEqual(by_id["count"], 0)
			self.assertEqual(by_id["orders"], [])

		# The ownership write changed no masking: a wrong-scoped key and an
		# unknown id are the same 404 as before acceptance (Recorded
		# Decision 5) — a non-owner without the capability id can retrieve
		# nothing at all.
		with self.assertRaises(RouteNotFoundError) as raised:
			self.orders.retrieve(self.order.order_id, self.foreign_key)
		self.assertEqual(raised.exception.status_code, 404)
		with self.assertRaises(RouteNotFoundError) as raised:
			self.orders.retrieve(f"order_{uuid.uuid4().hex}", self.key)
		self.assertEqual(raised.exception.status_code, 404)
