"""Phase 4 order-transfer request: the minting service over a locked order.

Focused service tests for ``OrderService.request_transfer``: the pending
``Ceto Order Transfer`` is minted for a **guest** order only, under the
order reference's row lock, with a UUIDv4 token whose plaintext reaches
only the ``ceto_order_transfer_requested`` hook (digest-only persistence,
Recorded Decision 10) and an explicit ``ORDER_TRANSFER_LIFETIME_DAYS``
window (Recorded Decision 11). The masking surface is the retrieve path's:
unknown ids, broken lineage, cancelled Sales Orders and wrong-scoped keys
are the same ``404 not_found``, while any owned order — by snapshot or by
the legacy cart fallback — is refused ``400 invalid_data`` (Recorded
Decision 9). A live pending request refuses a second one; an expired one
is removed under the lock and superseded by a fresh request. Nothing in
the order lineage is written (Recorded Decision 12), and the response is
the unchanged serialized ``StoreOrder``.

The fixture books a real guest order reference through the completion
shape (guest cart → submitted Quotation → submitted Sales Order) and runs
every request on the test site inside a single rolled-back transaction.
"""

import hashlib
import json
import uuid

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.service import OrderService
from ceto.services.orders.transfer import TRANSFER_REQUESTED_HOOK
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCartAddressPayload,
	StoreCompleteCart,
	StoreCreateCart,
	StoreUpdateCart,
)
from ceto.types.http.store.orders.manifest import ORDER_TRANSFER_LIFETIME_DAYS

ORDER_EMAIL = "guest@example.com"
DESCRIPTION = "Requested without an account; placed as guest@example.com."

#: Captured deliveries of the ``ceto_order_transfer_requested`` hook.
HOOK_CALLS: list[dict] = []


def record_transfer(**kwargs) -> None:
	HOOK_CALLS.append(kwargs)


def failing_transfer(**kwargs) -> None:
	HOOK_CALLS.append(kwargs)
	raise RuntimeError("the delivery channel refused the token")


def delivery_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_request.record_transfer"


def failing_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_request.failing_transfer"


class TestOrderTransferRequest(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.email = f"ceto.transfer.{uuid.uuid4().hex[:8]}@example.com"
		self.customer = self._make_customer()
		self.order = self._make_order_reference()
		HOOK_CALLS.clear()

	def _make_customer(self) -> str:
		"""The requesting Customer; the adapter would resolve it from the session."""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Order Transfer {uuid.uuid4().hex[:8]}",
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": "All Territories",
			}
		)
		customer.flags.ignore_permissions = True
		customer.insert()
		return customer.name

	def _make_order_reference(self):
		"""Place a real guest order through the completion flow.

		The completion books the order reference together with its line
		mappings, addresses and shipping charge — the full read model the
		serializer serves — and the order stays guest-owned: transfers
		recover exactly those orders.
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
						address_1="1 Transfer Way", city="Bangkok", country_code="th"
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

	def _request(self, **kwargs) -> dict:
		return self.orders.request_transfer(
			self.order.order_id,
			self.key,
			requested_by=self.customer,
			requester_email=self.email,
			**kwargs,
		)

	def _with_delivery(self, path: str = delivery_hook_path()):
		return self.patch_hooks({TRANSFER_REQUESTED_HOOK: [path]})

	def _pending_transfer(self):
		name = frappe.db.get_value(
			"Ceto Order Transfer", {"order_reference": self.order.name, "status": "Pending"}
		)
		return frappe.get_doc("Ceto Order Transfer", name) if name else None

	def _transfer_count(self) -> int:
		return frappe.db.count("Ceto Order Transfer", {"order_reference": self.order.name})

	def test_mints_the_pending_transfer_of_a_guest_order(self) -> None:
		with self._with_delivery():
			self._request(description=DESCRIPTION, update_order_email=True)

		transfer = self._pending_transfer()
		self.assertEqual(transfer.status, "Pending")
		self.assertEqual(transfer.order_reference, self.order.name)
		self.assertEqual(transfer.requested_by, self.customer)
		self.assertEqual(transfer.description, DESCRIPTION)
		# The recipient is the order's current email, snapshotted at request time.
		self.assertEqual(transfer.original_email, ORDER_EMAIL)
		self.assertEqual(transfer.new_email, self.email)
		self.assertEqual(self._transfer_count(), 1)

	def test_hands_the_plaintext_token_once_to_the_delivery_hook(self) -> None:
		with self._with_delivery():
			response = self._request()

		self.assertEqual(len(HOOK_CALLS), 1)
		delivery = HOOK_CALLS[0]
		self.assertEqual(delivery["order_id"], self.order.order_id)
		self.assertEqual(delivery["email"], ORDER_EMAIL)
		token = delivery["token"]
		# A minted UUIDv4, delivered verbatim — never re-derived.
		self.assertEqual(token, str(uuid.UUID(token)))
		self.assertEqual(uuid.UUID(token).version, 4)

		# Digest-only persistence (Recorded Decision 10): the record and the
		# response carry no plaintext anywhere.
		transfer = self._pending_transfer()
		self.assertEqual(transfer.token_hash, hashlib.sha256(token.encode()).hexdigest())
		self.assertNotIn(token, json.dumps(transfer.as_dict(), default=str))
		self.assertNotIn(token, json.dumps(response))

	def test_stores_the_explicit_pinned_window(self) -> None:
		with self._with_delivery():
			self._request()

		expires_at = get_datetime(self._pending_transfer().expires_at)
		delta = (expires_at - now_datetime()).total_seconds()
		self.assertAlmostEqual(delta, ORDER_TRANSFER_LIFETIME_DAYS * 24 * 3600, delta=120)

	def test_returns_the_unchanged_serialized_order(self) -> None:
		with self._with_delivery():
			response = self._request(update_order_email=True)

		self.assertEqual(
			json.dumps(response, sort_keys=True),
			json.dumps(self.orders.retrieve(self.order.order_id, self.key), sort_keys=True),
		)
		# The request changed nothing about the order itself.
		self.assertIsNone(response["customer_id"])
		self.assertEqual(response["email"], ORDER_EMAIL)

	def test_the_new_email_records_the_requester_only_when_requested(self) -> None:
		with self._with_delivery():
			self._request(update_order_email=True)
		self.assertEqual(self._pending_transfer().new_email, self.email)

	def test_description_and_new_email_stay_optional(self) -> None:
		with self._with_delivery():
			self._request()

		transfer = self._pending_transfer()
		self.assertIsNone(transfer.description)
		self.assertIsNone(transfer.new_email)

	def test_without_a_receiver_the_request_stays_pending(self) -> None:
		with self.patch_hooks({TRANSFER_REQUESTED_HOOK: []}):
			self._request()

		self.assertIsNotNone(self._pending_transfer())

	def test_a_failing_receiver_fails_the_request_and_rolls_the_insert_back(self) -> None:
		with self._with_delivery(failing_hook_path()), self.assertRaises(RuntimeError):
			self._request()

		# The receiver failure propagated inside the open transaction: the
		# API layer's error rollback removes the just-inserted request.
		frappe.db.rollback()
		self.assertEqual(self._transfer_count(), 0)

	def test_an_unknown_order_is_masked_as_not_found(self) -> None:
		with self._with_delivery():
			with self.assertRaises(RouteNotFoundError) as raised:
				self.orders.request_transfer(
					f"order_{uuid.uuid4().hex}", self.key, requested_by=self.customer
				)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(HOOK_CALLS, [])
		self.assertEqual(self._transfer_count(), 0)

	def test_a_wrong_scoped_key_masks_the_order_as_not_found(self) -> None:
		foreign = CartPublishableKey(region_id="reg_elsewhere", sales_channel_id="sc_elsewhere")

		with self._with_delivery():
			with self.assertRaises(RouteNotFoundError) as raised:
				self.orders.request_transfer(self.order.order_id, foreign, requested_by=self.customer)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(HOOK_CALLS, [])
		self.assertEqual(self._transfer_count(), 0)

	def test_a_cancelled_order_is_masked_as_not_found(self) -> None:
		frappe.db.set_value("Sales Order", self.order.sales_order, "docstatus", 2)

		with self._with_delivery():
			with self.assertRaises(RouteNotFoundError) as raised:
				self._request()

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(self._transfer_count(), 0)

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		frappe.db.set_value(
			"Ceto Order Reference", self.order.name, "sales_order", f"SO-{uuid.uuid4().hex[:8]}"
		)

		with self._with_delivery():
			with self.assertRaises(RouteNotFoundError) as raised:
				self._request()

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(self._transfer_count(), 0)

	def test_an_owned_order_is_refused_as_invalid_data(self) -> None:
		frappe.db.set_value("Ceto Order Reference", self.order.name, "owner_customer", self.customer)

		with self._with_delivery():
			with self.assertRaises(InvalidDataError) as raised:
				self._request()

		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(HOOK_CALLS, [])
		self.assertEqual(self._transfer_count(), 0)

	def test_an_owned_legacy_order_is_refused_as_invalid_data(self) -> None:
		# No snapshot, but the completed cart's owner resolves: effectively owned.
		frappe.db.set_value("Ceto Cart Reference", self.order.cart_id, "owner_customer", self.customer)

		with self._with_delivery():
			with self.assertRaises(InvalidDataError) as raised:
				self._request()

		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._transfer_count(), 0)

	def test_a_second_request_while_pending_is_refused(self) -> None:
		with self._with_delivery():
			self._request()
		live = self._pending_transfer()

		with self._with_delivery():
			with self.assertRaises(InvalidDataError) as raised:
				self._request(description="Second attempt", update_order_email=True)

		self.assertEqual(raised.exception.status_code, 400)
		# The live request is untouched: still exactly one, never re-minted —
		# the newer payload's fields must not silently replace its state.
		self.assertEqual(self._transfer_count(), 1)
		self.assertIsNone(self._pending_transfer().new_email)
		self.assertEqual(self._pending_transfer().name, live.name)
		self.assertEqual(len(HOOK_CALLS), 1)

	def test_an_expired_request_is_superseded_by_a_fresh_one(self) -> None:
		with self._with_delivery():
			self._request()
		first = self._pending_transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", first.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)

		with self._with_delivery():
			self._request()

		# The expired record is removed under the lock and the fresh request
		# takes its place with its own minted token and window.
		self.assertFalse(frappe.db.exists("Ceto Order Transfer", first.name))
		records = frappe.get_all(
			"Ceto Order Transfer", filters={"order_reference": self.order.name}, pluck="name"
		)
		self.assertEqual(len(records), 1)
		fresh = frappe.get_doc("Ceto Order Transfer", records[0])
		self.assertEqual(fresh.status, "Pending")
		self.assertNotEqual(fresh.token_hash, first.token_hash)
		self.assertEqual(fresh.token_hash, hashlib.sha256(HOOK_CALLS[1]["token"].encode()).hexdigest())
		delta = (get_datetime(fresh.expires_at) - now_datetime()).total_seconds()
		self.assertAlmostEqual(delta, ORDER_TRANSFER_LIFETIME_DAYS * 24 * 3600, delta=120)

	def test_the_order_lineage_is_never_written(self) -> None:
		before_reference = frappe.db.get_value(
			"Ceto Order Reference",
			self.order.name,
			["owner_customer", "sales_order", "cart_id"],
			as_dict=True,
		)
		before_cart = frappe.db.get_value(
			"Ceto Cart Reference",
			self.order.cart_id,
			["owner_customer", "region_id", "sales_channel_id"],
			as_dict=True,
		)
		before_sales_order = frappe.db.get_value(
			"Sales Order",
			self.order.sales_order,
			["customer", "contact_email", "docstatus"],
			as_dict=True,
		)

		with self._with_delivery():
			response = self._request(update_order_email=True)

		self.assertEqual(
			frappe.db.get_value(
				"Ceto Order Reference",
				self.order.name,
				["owner_customer", "sales_order", "cart_id"],
				as_dict=True,
			),
			before_reference,
		)
		self.assertEqual(
			frappe.db.get_value(
				"Ceto Cart Reference",
				self.order.cart_id,
				["owner_customer", "region_id", "sales_channel_id"],
				as_dict=True,
			),
			before_cart,
		)
		self.assertEqual(
			frappe.db.get_value(
				"Sales Order",
				self.order.sales_order,
				["customer", "contact_email", "docstatus"],
				as_dict=True,
			),
			before_sales_order,
		)
		self.assertIsNone(response["customer_id"])
