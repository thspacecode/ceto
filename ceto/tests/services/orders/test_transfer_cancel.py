"""Phase 4 order-transfer cancel: the requester's removal of the pending state.

Focused service tests for ``OrderService.cancel_transfer``: the pending
``Ceto Order Transfer`` is found under the order reference's row lock
regardless of ``expires_at`` — an expired request stays cancellable by its
requester (Recorded Decision 11) — and deleting the record destroys the
digest-only token with it (Recorded Decision 10); cancellation is the
record's death, never a status flip. The masking surface is the retrieve
path's: unknown ids, broken lineage, cancelled Sales Orders and
wrong-scoped keys are the same ``404 not_found``. A missing pending
request is ``400 invalid_data`` — including the replayed cancel after a
successful one — and only the recorded ``requested_by`` customer may
cancel: any other caller is ``403 not_allowed`` and consumes nothing. An
error at the delete leaves the record (and its digest) exactly as the
request minted it, so the API layer's rollback has nothing to repair.
Nothing in the order lineage is written (Recorded Decision 12), and the
response is the unchanged serialized ``StoreOrder``.

The fixture books a real guest order reference through the completion
shape (guest cart → submitted Quotation → submitted Sales Order), mints
each pending transfer through the real request service and cancels on the
test site inside a single rolled-back transaction.
"""

import hashlib
import json
import uuid
from unittest import mock

import frappe
from frappe.utils import add_to_date, now_datetime

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import InvalidDataError, NotAllowedError, RouteNotFoundError
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

ORDER_EMAIL = "guest@example.com"
DESCRIPTION = "Requested without an account; placed as guest@example.com."

#: Captured deliveries of the ``ceto_order_transfer_requested`` hook, so the
#: minted token's digest can be followed to its destruction.
HOOK_CALLS: list[dict] = []


def record_transfer(**kwargs) -> None:
	HOOK_CALLS.append(kwargs)


def delivery_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_cancel.record_transfer"


class TestOrderTransferCancel(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.customer = self._make_customer()
		self.stranger = self._make_customer()
		self.order = self._make_order_reference()
		HOOK_CALLS.clear()

	def _make_customer(self) -> str:
		"""A Customer; the adapter would resolve the caller from the session."""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Order Transfer Cancel {uuid.uuid4().hex[:8]}",
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
		mappings, addresses and shipping charge, and the order stays
		guest-owned: transfers recover exactly those orders.
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
		"""Mint the pending transfer through the real request service."""
		with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [delivery_hook_path()]}):
			return self.orders.request_transfer(
				self.order.order_id,
				self.key,
				requested_by=self.customer,
				requester_email=f"ceto.cancel.{uuid.uuid4().hex[:8]}@example.com",
				**kwargs,
			)

	def _cancel(self, requested_by: str | None = None) -> dict:
		return self.orders.cancel_transfer(
			self.order.order_id, self.key, requested_by=requested_by or self.customer
		)

	def _pending_transfer(self):
		name = frappe.db.get_value(
			"Ceto Order Transfer", {"order_reference": self.order.name, "status": "Pending"}
		)
		return frappe.get_doc("Ceto Order Transfer", name) if name else None

	def _transfer_count(self) -> int:
		return frappe.db.count("Ceto Order Transfer", {"order_reference": self.order.name})

	def test_the_requester_cancels_the_pending_transfer(self) -> None:
		self._request()
		pending = self._pending_transfer()

		self._cancel()

		# The record is gone, not flipped to a terminal status: a cancelled
		# transfer leaves no addressable row behind.
		self.assertEqual(self._transfer_count(), 0)
		self.assertFalse(frappe.db.exists("Ceto Order Transfer", pending.name))

	def test_deleting_the_record_destroys_the_digest_only_token(self) -> None:
		self._request()
		digest = hashlib.sha256(HOOK_CALLS[0]["token"].encode()).hexdigest()
		self.assertEqual(self._pending_transfer().token_hash, digest)

		self._cancel()

		# The record is the only carrier of the digest (Recorded Decision
		# 10): deleting it destroys the single-use credential, and no
		# plaintext ever existed to sweep up.
		self.assertIsNone(frappe.db.get_value("Ceto Order Transfer", {"token_hash": digest}))
		self.assertEqual(self._transfer_count(), 0)

	def test_returns_the_unchanged_serialized_order(self) -> None:
		self._request()

		response = self._cancel()

		self.assertEqual(
			json.dumps(response, sort_keys=True),
			json.dumps(self.orders.retrieve(self.order.order_id, self.key), sort_keys=True),
		)
		# The cancel changed nothing about the order itself.
		self.assertIsNone(response["customer_id"])
		self.assertEqual(response["email"], ORDER_EMAIL)

	def test_the_order_lineage_is_never_written(self) -> None:
		self._request()
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

		self._cancel()

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

	def test_a_cancel_without_any_request_is_invalid_data(self) -> None:
		with self.assertRaises(InvalidDataError) as raised:
			self._cancel()

		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._transfer_count(), 0)

	def test_a_replayed_cancel_fails_as_missing_pending(self) -> None:
		self._request()
		self._cancel()

		with self.assertRaises(InvalidDataError) as raised:
			self._cancel()

		# The lifecycle is terminal (orders field-mapping, Transfer
		# lifecycle): after a cancel no pending transfer remains, so the
		# replay is the missing-pending refusal, not an idempotent no-op.
		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._transfer_count(), 0)

	def test_only_the_requester_may_cancel(self) -> None:
		self._request()
		live = self._pending_transfer()

		with self.assertRaises(NotAllowedError) as raised:
			self._cancel(requested_by=self.stranger)

		self.assertEqual(raised.exception.status_code, 403)
		# The refusal consumed nothing: the record — its digest included —
		# stays pending, and the requester can still cancel it.
		self.assertEqual(self._transfer_count(), 1)
		kept = self._pending_transfer()
		self.assertEqual(kept.name, live.name)
		self.assertEqual(kept.token_hash, live.token_hash)
		self._cancel()
		self.assertEqual(self._transfer_count(), 0)

	def test_an_expired_request_remains_cancellable(self) -> None:
		self._request()
		expired = self._pending_transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", expired.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)

		self._cancel()

		# Recorded Decision 11: expiry frees the order, but it is the
		# requester's cancel that removes the expired record — the pending
		# scan never filters on the window.
		self.assertEqual(self._transfer_count(), 0)

	def test_an_unknown_order_is_masked_as_not_found(self) -> None:
		self._request()

		with self.assertRaises(RouteNotFoundError) as raised:
			self.orders.cancel_transfer(f"order_{uuid.uuid4().hex}", self.key, requested_by=self.customer)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(self._transfer_count(), 1)

	def test_a_wrong_scoped_key_masks_the_order_as_not_found(self) -> None:
		self._request()
		foreign = CartPublishableKey(region_id="reg_elsewhere", sales_channel_id="sc_elsewhere")

		with self.assertRaises(RouteNotFoundError) as raised:
			self.orders.cancel_transfer(self.order.order_id, foreign, requested_by=self.customer)

		self.assertEqual(raised.exception.status_code, 404)
		# A foreign order simply does not exist for that key: the pending
		# record survives untouched.
		self.assertEqual(self._transfer_count(), 1)

	def test_a_cancelled_order_is_masked_as_not_found(self) -> None:
		self._request()
		frappe.db.set_value("Sales Order", self.order.sales_order, "docstatus", 2)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._cancel()

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(self._transfer_count(), 1)

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		self._request()
		frappe.db.set_value(
			"Ceto Order Reference", self.order.name, "sales_order", f"SO-{uuid.uuid4().hex[:8]}"
		)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._cancel()

		self.assertEqual(raised.exception.status_code, 404)
		self.assertEqual(self._transfer_count(), 1)

	def test_an_error_at_the_delete_leaves_the_record_untouched(self) -> None:
		self._request()
		live = self._pending_transfer()

		with mock.patch("frappe.delete_doc", side_effect=RuntimeError("the delete failed")):
			with self.assertRaises(RuntimeError):
				self._cancel()

		# Nothing half-written survives: the record — digest included — is
		# exactly as the request minted it, so the API layer's error
		# rollback has nothing to repair.
		kept = self._pending_transfer()
		self.assertEqual(kept.name, live.name)
		self.assertEqual(kept.token_hash, live.token_hash)
		self.assertEqual(kept.status, "Pending")

	def test_a_cancelled_request_frees_the_order_for_a_fresh_one(self) -> None:
		self._request()
		first = self._pending_transfer()
		self._cancel()

		self._request(description=DESCRIPTION)

		# The same locked scan that refuses a second live request now mints
		# a fresh one: cancel frees the order exactly like expiry does.
		records = frappe.get_all(
			"Ceto Order Transfer", filters={"order_reference": self.order.name}, pluck="name"
		)
		self.assertEqual(len(records), 1)
		fresh = frappe.get_doc("Ceto Order Transfer", records[0])
		self.assertEqual(fresh.status, "Pending")
		self.assertEqual(fresh.description, DESCRIPTION)
		self.assertNotEqual(fresh.name, first.name)
		self.assertNotEqual(fresh.token_hash, first.token_hash)
