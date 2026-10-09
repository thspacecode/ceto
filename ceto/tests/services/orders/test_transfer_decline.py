"""Phase 5 order-transfer decline: the holder's refusal over a locked order.

Focused service tests for ``OrderService.decline_transfer``: the pending
``Ceto Order Transfer`` is refused only by its own single-use token,
presented against the path order under the order reference's row lock —
the same lock, masked resolution and credential gates as acceptance. The
token is only ever hashed (Recorded Decision 10); every failing
credential — wrong, expired, replayed-accepted, replayed-declined — is
the same ``403 not_allowed`` ``Invalid token.`` without mutation, while a
digest matching no record lands on ``not_allowed`` for as long as a live
pending request exists and on ``400 invalid_data`` once none does (orders
field-mapping, Transfer lifecycle replay). The masking surface is the
retrieve path's: unknown ids, broken lineage, cancelled Sales Orders and
wrong-scoped keys are the same ``404 not_found``. The refusal is one
write — the record closes ``Declined`` — while ownership, the order
reference's email and ``modified`` stamp, the cart reference and the
Sales Order are untouched (Recorded Decision 12), and the
``ceto_order_transfer_declined`` hook announces the refusal inside the
transaction with the same safe payload shape as acceptance, never any
token material.

The fixture books a real guest order reference through the completion
shape (guest cart → submitted Quotation → submitted Sales Order), mints
each pending transfer through the real request service and declines on
the test site inside a single rolled-back transaction.
"""

import hashlib
import json
import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import InvalidDataError, NotAllowedError, RouteNotFoundError
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.service import OrderService
from ceto.services.orders.transfer import TRANSFER_DECLINED_HOOK, TRANSFER_REQUESTED_HOOK
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

#: Captured deliveries of the transfer hooks.
REQUEST_HOOK_CALLS: list[dict] = []
DECLINED_HOOK_CALLS: list[dict] = []


def record_requested(**kwargs) -> None:
	REQUEST_HOOK_CALLS.append(kwargs)


def record_declined(**kwargs) -> None:
	DECLINED_HOOK_CALLS.append(kwargs)


def record_declined_with_status(order_id, **kwargs) -> None:
	"""Record the payload plus the status the transaction has already written."""
	DECLINED_HOOK_CALLS.append(
		{
			**kwargs,
			"status_at_delivery": frappe.db.get_value(
				"Ceto Order Transfer", {"transfer_id": kwargs["transfer_id"]}, "status"
			),
		}
	)


def failing_declined(order_id, **kwargs) -> None:
	"""Record the payload with the status view, then refuse the notice."""
	DECLINED_HOOK_CALLS.append(
		{
			**kwargs,
			"status_at_delivery": frappe.db.get_value(
				"Ceto Order Transfer", {"transfer_id": kwargs["transfer_id"]}, "status"
			),
		}
	)
	raise RuntimeError("the decline channel refused the notice")


def requested_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_decline.record_requested"


def declined_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_decline.record_declined"


def declined_with_status_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_decline.record_declined_with_status"


def failing_declined_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_decline.failing_declined"


class TestOrderTransferDecline(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.email = f"ceto.decline.{uuid.uuid4().hex[:8]}@example.com"
		self.customer = self._make_customer()
		self.order = self._make_order_reference()
		REQUEST_HOOK_CALLS.clear()
		DECLINED_HOOK_CALLS.clear()

	def _make_customer(self) -> str:
		"""A Customer; the adapter would resolve the caller from the session."""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Order Transfer Decline {uuid.uuid4().hex[:8]}",
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

	def _request(self, order_id: str | None = None, **kwargs) -> str:
		"""Mint the pending transfer through the real request service; return the token."""
		with self.patch_hooks({TRANSFER_REQUESTED_HOOK: [requested_hook_path()]}):
			self.orders.request_transfer(
				order_id or self.order.order_id,
				self.key,
				requested_by=self.customer,
				requester_email=self.email,
				**kwargs,
			)
		return REQUEST_HOOK_CALLS[-1]["token"]

	def _decline(self, token: str, order_id: str | None = None, key=None) -> dict:
		return self.orders.decline_transfer(order_id or self.order.order_id, key or self.key, token=token)

	def _accept(self, token: str, order_id: str | None = None, key=None) -> dict:
		return self.orders.accept_transfer(order_id or self.order.order_id, key or self.key, token=token)

	def _transfer(self):
		name = frappe.db.get_value(
			"Ceto Order Transfer", {"order_reference": self.order.name, "status": "Pending"}
		)
		return frappe.get_doc("Ceto Order Transfer", name) if name else None

	def _record(self) -> dict:
		"""The order's single transfer record, whatever status it carries."""
		name = frappe.db.get_value("Ceto Order Transfer", {"order_reference": self.order.name})
		return frappe.get_doc("Ceto Order Transfer", name) if name else {}

	def _reference_row(self) -> dict:
		return frappe.db.get_value(
			"Ceto Order Reference",
			self.order.name,
			["owner_customer", "email", "modified"],
			as_dict=True,
		)

	def test_decline_closes_the_record_declined_and_leaves_ownership_alone(self) -> None:
		token = self._request()

		response = self._decline(token)

		# The refusal is terminal for the record — never a deletion — and
		# the order stays guest-owned: the requester gains nothing.
		self.assertEqual(response["customer_id"], None)
		record = self._record()
		self.assertEqual(record.status, "Declined")
		self.assertEqual(record.requested_by, self.customer)
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_decline_returns_the_unchanged_serialized_order(self) -> None:
		token = self._request(update_order_email=True)
		before = self.orders.retrieve(self.order.order_id, self.key)

		response = self._decline(token)

		# Byte-identical to the pre-decline and post-decline reads alike:
		# nothing in the order lineage moved to answer the refusal.
		self.assertEqual(
			json.dumps(response, sort_keys=True),
			json.dumps(before, sort_keys=True),
		)
		self.assertEqual(
			json.dumps(response, sort_keys=True),
			json.dumps(self.orders.retrieve(self.order.order_id, self.key), sort_keys=True),
		)
		self.assertEqual(response["email"], ORDER_EMAIL)

	def test_decline_never_touches_the_reference_email_or_modified_stamp(self) -> None:
		token = self._request(update_order_email=True)
		before = self._reference_row()

		self._decline(token)

		# Even a declined ``update_order_email`` records nothing: the
		# would-be address stays on the record only (Recorded Decision 12).
		self.assertEqual(self._reference_row(), before)
		self.assertIsNone(self._reference_row()["email"])

	def test_the_declined_record_is_terminal_not_deleted(self) -> None:
		token = self._request()
		pending = self._transfer()
		self._decline(token)

		# Exactly one record remains, closed and addressable (Recorded
		# Decision 11): its digest is what a replayed token still matches.
		self.assertEqual(self._record().status, "Declined")
		self.assertEqual(self._record().name, pending.name)
		self.assertEqual(self._record().token_hash, pending.token_hash)
		self.assertIsNone(self._transfer())

	def test_a_replayed_decline_fails_as_not_allowed(self) -> None:
		token = self._request()
		self._decline(token)

		with self.assertRaises(NotAllowedError) as raised:
			self._decline(token)

		# The terminal record still carries the digest: the replay is the
		# same invalid-token refusal and the first refusal stands.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertEqual(self._record().status, "Declined")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_an_accepted_replay_of_a_declined_token_is_not_allowed(self) -> None:
		token = self._request()
		self._decline(token)

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(token)

		# Cross-operation replay: the decline consumed the credential, so
		# acceptance of the same token is the same not_allowed refusal.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_a_wrong_token_is_not_allowed_without_mutation(self) -> None:
		token = self._request()
		pending = self._transfer()

		with self.assertRaises(NotAllowedError) as raised:
			self._decline(f"{token[:-1]}{'0' if token[-1] != '0' else '1'}")

		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		kept = self._transfer()
		self.assertEqual(kept.name, pending.name)
		self.assertEqual(kept.token_hash, pending.token_hash)
		self.assertEqual(self._record().status, "Pending")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_an_expired_token_is_the_same_invalid_token_refusal(self) -> None:
		token = self._request()
		pending = self._transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", pending.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)

		with self.assertRaises(NotAllowedError) as raised:
			self._decline(token)

		# Indistinguishable from a wrong token (Recorded Decision 11), and
		# it mutates nothing: the expired record stays pending — the
		# requester's cancel, not the failed decline, removes it.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		kept = self._transfer()
		self.assertEqual(kept.name, pending.name)
		self.assertEqual(kept.token_hash, pending.token_hash)
		self.assertEqual(self._record().status, "Pending")

	def test_a_foreign_order_token_is_not_allowed_here(self) -> None:
		token = self._request()
		other = self._make_order_reference()
		foreign = self._request(order_id=other.order_id)

		with self.assertRaises(NotAllowedError) as raised:
			self._decline(foreign)

		# The scan is keyed on the path order's reference: another order's
		# credential is just a wrong token here, and consumes nothing.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertEqual(self._record().status, "Pending")
		self.assertIsNotNone(
			frappe.db.get_value("Ceto Order Transfer", {"order_reference": other.name, "status": "Pending"})
		)

		response = self._decline(token)
		self.assertEqual(response["customer_id"], None)
		self.assertEqual(self._record().status, "Declined")

	def test_decline_without_any_request_is_invalid_data(self) -> None:
		with self.assertRaises(InvalidDataError) as raised:
			self._decline(str(uuid.uuid4()))

		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._record(), {})

	def test_decline_after_a_cancel_is_invalid_data(self) -> None:
		token = self._request()
		self.orders.cancel_transfer(self.order.order_id, self.key, requested_by=self.customer)

		with self.assertRaises(InvalidDataError) as raised:
			self._decline(token)

		# The cancel deleted the record that carried the digest and nothing
		# replaced it: the replay is the missing-pending refusal, not a
		# credential match (upstream: decline requires a pending change).
		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._record(), {})

	def test_a_wrong_token_after_a_decline_is_invalid_data(self) -> None:
		token = self._request()
		self._decline(token)

		with self.assertRaises(InvalidDataError) as raised:
			self._decline(str(uuid.uuid4()))

		# Upstream: after decline no pending transfer remains, so a further
		# decline is invalid_data — only the refused token itself still
		# matches a terminal record and gets not_allowed.
		self.assertEqual(raised.exception.status_code, 400)

	def test_a_superseded_token_is_just_a_wrong_token_while_a_request_is_live(self) -> None:
		first = self._request()
		pending = self._transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", pending.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)
		second = self._request()
		self.assertNotEqual(second, first)

		with self.assertRaises(NotAllowedError) as raised:
			self._decline(first)

		# The supersession deleted the record that carried the first digest:
		# against the fresh live request the old token is a wrong credential.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self._decline(second)
		self.assertEqual(self._record().status, "Declined")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_an_unknown_order_is_masked_as_not_found(self) -> None:
		token = self._request()

		with self.assertRaises(RouteNotFoundError) as raised:
			self._decline(token, order_id=f"order_{uuid.uuid4().hex}")

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_a_wrong_scoped_key_masks_the_order_as_not_found(self) -> None:
		token = self._request()
		foreign = CartPublishableKey(region_id="reg_elsewhere", sales_channel_id="sc_elsewhere")

		with self.assertRaises(RouteNotFoundError) as raised:
			self._decline(token, key=foreign)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_a_cancelled_order_is_masked_as_not_found(self) -> None:
		token = self._request()
		frappe.db.set_value("Sales Order", self.order.sales_order, "docstatus", 2)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._decline(token)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		token = self._request()
		frappe.db.set_value(
			"Ceto Order Reference", self.order.name, "sales_order", f"SO-{uuid.uuid4().hex[:8]}"
		)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._decline(token)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_decline_never_touches_the_cart_or_sales_order(self) -> None:
		token = self._request(update_order_email=True)
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

		self._decline(token)

		# The refusal writes the transfer record only (Recorded Decision 12):
		# the immutable cart history keeps its completer, the Sales Order its
		# birth customer and contact.
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
		self.assertEqual(frappe.db.get_value("Sales Order", self.order.sales_order, "docstatus"), 1)

	def test_a_fresh_request_after_a_decline_mints_a_winning_token(self) -> None:
		first = self._request()
		self._decline(first)

		# The refusal left the order guest-owned, so the requester can ask
		# again (Recorded Decision 11: terminal records stay addressable
		# beside a new pending one) and the fresh token consumes normally.
		second = self._request()
		self.assertNotEqual(second, first)
		self.assertEqual(frappe.db.count("Ceto Order Transfer", {"order_reference": self.order.name}), 2)
		self.assertIsNotNone(
			frappe.db.get_value(
				"Ceto Order Transfer", {"order_reference": self.order.name, "status": "Declined"}
			)
		)
		self.assertIsNotNone(self._transfer())

		response = self._accept(second)
		self.assertEqual(response["customer_id"], self.customer)
		self.assertEqual(self._reference_row()["owner_customer"], self.customer)

	def test_the_declined_token_stays_not_allowed_beside_a_fresh_request(self) -> None:
		first = self._request()
		self._decline(first)
		self._request()

		for replay in (self._decline, self._accept):
			with self.subTest(operation=replay.__name__):
				with self.assertRaises(NotAllowedError) as raised:
					replay(first)

				# The terminal record still carries the digest: against the
				# fresh live request the refused token stays not_allowed.
				self.assertEqual(raised.exception.status_code, 403)
				self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_the_declined_hook_receives_exactly_the_safe_payload(self) -> None:
		token = self._request()
		pending = self._transfer()

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: [declined_hook_path()]}):
			self._decline(token)

		self.assertEqual(len(DECLINED_HOOK_CALLS), 1)
		payload = DECLINED_HOOK_CALLS[0]
		self.assertEqual(set(payload), {"order_id", "transfer_id", "owner_customer", "email"})
		self.assertEqual(payload["order_id"], self.order.order_id)
		self.assertEqual(payload["transfer_id"], pending.transfer_id)
		self.assertEqual(payload["owner_customer"], self.customer)
		self.assertIsNone(payload["email"])

	def test_the_declined_payload_carries_the_recorded_address(self) -> None:
		token = self._request(update_order_email=True)

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: [declined_hook_path()]}):
			self._decline(token)

		# The would-be address the refusal turned down: the stored
		# ``new_email``, never a write on the order reference.
		self.assertEqual(DECLINED_HOOK_CALLS[0]["email"], self.email)

	def test_the_declined_hook_never_carries_token_material(self) -> None:
		token = self._request()
		digest = hashlib.sha256(token.encode()).hexdigest()

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: [declined_hook_path()]}):
			self._decline(token)

		# The deliberate safe payload: neither the plaintext token nor its
		# digest ever reaches a receiver (Recorded Decision 10).
		rendered = json.dumps(DECLINED_HOOK_CALLS)
		self.assertNotIn(token, rendered)
		self.assertNotIn(digest, rendered)

	def test_the_declined_hook_fires_inside_the_transaction_after_the_write(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: [declined_with_status_hook_path()]}):
			self._decline(token)

		# The receiver already sees the record closed Declined: the
		# announcement rides the same open transaction, after the write.
		self.assertEqual(DECLINED_HOOK_CALLS[0]["status_at_delivery"], "Declined")

	def test_without_a_receiver_the_decline_still_completes(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: []}):
			self._decline(token)

		self.assertEqual(self._record().status, "Declined")
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_a_failing_receiver_fails_the_decline_and_rolls_the_write_back(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_DECLINED_HOOK: [failing_declined_hook_path()]}):
			with self.assertRaises(RuntimeError):
				self._decline(token)

		# The receiver had already seen the closed record inside the open
		# transaction when it failed.
		self.assertEqual(DECLINED_HOOK_CALLS[0]["status_at_delivery"], "Declined")

		# The API layer's error rollback erases the whole decline: the
		# closed record is not committed — no half-declined state survives
		# (the committed fixture is what stays).
		frappe.db.rollback()
		self.assertEqual(frappe.db.count("Ceto Order Transfer", {"order_reference": self.order.name}), 0)
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", self.order.name, "owner_customer"))
