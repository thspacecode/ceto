"""Phase 5 order-transfer accept: the holder's consent over a locked order.

Focused service tests for ``OrderService.accept_transfer``: the pending
``Ceto Order Transfer`` is consumed only by its own single-use token,
presented against the path order under the order reference's row lock.
The token is only ever hashed (Recorded Decision 10); every failing
credential — wrong, expired, replayed-accepted, declined — is the same
``403 not_allowed`` ``Invalid token.`` without mutation, while a digest
matching no record lands on ``not_allowed`` for as long as a live pending
request exists and on ``400 invalid_data`` once none does (orders
field-mapping, Transfer lifecycle replay). The masking surface is the
retrieve path's: unknown ids, broken lineage, cancelled Sales Orders and
wrong-scoped keys are the same ``404 not_found``. The winner is consumed
atomically — the order reference's ``owner_customer`` becomes the stored
requester (optionally its recorded email) and the record closes
``Accepted`` — while the cart reference and the Sales Order are never
written (Recorded Decision 12), and the ``ceto_order_transfer_accepted``
hook announces the consumed transfer inside the transaction with a
payload that never carries token material.

The fixture books a real guest order reference through the completion
shape (guest cart → submitted Quotation → submitted Sales Order), mints
each pending transfer through the real request service and accepts on
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
from ceto.services.orders.transfer import TRANSFER_ACCEPTED_HOOK, TRANSFER_REQUESTED_HOOK
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
ACCEPTED_HOOK_CALLS: list[dict] = []


def record_requested(**kwargs) -> None:
	REQUEST_HOOK_CALLS.append(kwargs)


def record_accepted(**kwargs) -> None:
	ACCEPTED_HOOK_CALLS.append(kwargs)


def record_accepted_with_owner(order_id, **kwargs) -> None:
	"""Record the payload plus the owner the transaction has already written."""
	ACCEPTED_HOOK_CALLS.append(
		{
			**kwargs,
			"owner_at_delivery": frappe.db.get_value(
				"Ceto Order Reference", {"order_id": order_id}, "owner_customer"
			),
		}
	)


def failing_accepted(order_id, **kwargs) -> None:
	"""Record the payload with the owner view, then refuse the notice."""
	ACCEPTED_HOOK_CALLS.append(
		{
			**kwargs,
			"owner_at_delivery": frappe.db.get_value(
				"Ceto Order Reference", {"order_id": order_id}, "owner_customer"
			),
		}
	)
	raise RuntimeError("the acceptance channel refused the notice")


def requested_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_accept.record_requested"


def accepted_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_accept.record_accepted"


def accepted_with_owner_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_accept.record_accepted_with_owner"


def failing_accepted_hook_path() -> str:
	return "ceto.tests.services.orders.test_transfer_accept.failing_accepted"


class TestOrderTransferAccept(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.email = f"ceto.accept.{uuid.uuid4().hex[:8]}@example.com"
		self.customer = self._make_customer()
		self.order = self._make_order_reference()
		REQUEST_HOOK_CALLS.clear()
		ACCEPTED_HOOK_CALLS.clear()

	def _make_customer(self) -> str:
		"""A Customer; the adapter would resolve the caller from the session."""
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Order Transfer Accept {uuid.uuid4().hex[:8]}",
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
			"Ceto Order Reference", self.order.name, ["owner_customer", "email"], as_dict=True
		)

	def test_accept_moves_ownership_to_the_requested_customer(self) -> None:
		token = self._request()

		response = self._accept(token)

		# The stored requester becomes the owner — never a payload-supplied
		# recipient (Recorded Decision 9) — and the record closes terminal.
		self.assertEqual(response["customer_id"], self.customer)
		self.assertEqual(self._reference_row()["owner_customer"], self.customer)
		record = self._record()
		self.assertEqual(record.status, "Accepted")
		self.assertEqual(record.requested_by, self.customer)

	def test_the_consumed_record_is_terminal_not_deleted(self) -> None:
		self._request()
		self._accept(REQUEST_HOOK_CALLS[0]["token"])

		# Exactly one record remains, closed and addressable (Recorded
		# Decision 11): its digest is what a replayed token still matches.
		self.assertEqual(self._record().status, "Accepted")
		self.assertIsNone(self._transfer())

	def test_accept_returns_the_freshly_serialized_order(self) -> None:
		token = self._request(update_order_email=True)

		response = self._accept(token)

		self.assertEqual(
			json.dumps(response, sort_keys=True),
			json.dumps(self.orders.retrieve(self.order.order_id, self.key), sort_keys=True),
		)
		# The response is the reloaded state, not the pre-acceptance read.
		self.assertEqual(response["customer_id"], self.customer)
		self.assertEqual(response["email"], self.email)

	def test_accept_records_the_stored_new_email(self) -> None:
		token = self._request(update_order_email=True)

		response = self._accept(token)

		self.assertEqual(self._reference_row()["email"], self.email)
		self.assertEqual(response["email"], self.email)
		# The Sales Order keeps its birth contact lineage (Recorded Decision 12).
		self.assertEqual(
			frappe.db.get_value("Sales Order", self.order.sales_order, "contact_email"), ORDER_EMAIL
		)

	def test_accept_without_update_order_email_keeps_the_birth_email(self) -> None:
		token = self._request()

		response = self._accept(token)

		self.assertIsNone(self._reference_row()["email"])
		self.assertEqual(response["email"], ORDER_EMAIL)

	def test_a_wrong_token_is_not_allowed_without_mutation(self) -> None:
		token = self._request()
		pending = self._transfer()

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(f"{token[:-1]}{'0' if token[-1] != '0' else '1'}")

		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		kept = self._transfer()
		self.assertEqual(kept.name, pending.name)
		self.assertEqual(kept.token_hash, pending.token_hash)
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_an_expired_token_is_the_same_invalid_token_refusal(self) -> None:
		token = self._request()
		pending = self._transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", pending.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(token)

		# Indistinguishable from a wrong token (Recorded Decision 11), and
		# it mutates nothing: the expired record stays pending — the
		# requester's cancel, not the failed accept, removes it.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		kept = self._transfer()
		self.assertEqual(kept.name, pending.name)
		self.assertEqual(kept.token_hash, pending.token_hash)
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_a_replayed_accept_fails_as_not_allowed(self) -> None:
		token = self._request()
		self._accept(token)

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(token)

		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		# The first acceptance stands; the replay moved nothing.
		self.assertEqual(self._reference_row()["owner_customer"], self.customer)

	def test_a_declined_token_is_not_allowed(self) -> None:
		token = self._request()
		pending = self._transfer()
		# The decline surface closes a record exactly like this: terminal,
		# digest kept (Recorded Decision 11).
		frappe.db.set_value("Ceto Order Transfer", pending.name, "status", "Declined")

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(token)

		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertIsNone(self._reference_row()["owner_customer"])
		self.assertEqual(self._record().status, "Declined")

	def test_accept_without_any_request_is_invalid_data(self) -> None:
		with self.assertRaises(InvalidDataError) as raised:
			self._accept(str(uuid.uuid4()))

		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._record(), {})

	def test_accept_after_a_cancel_is_invalid_data(self) -> None:
		token = self._request()
		self.orders.cancel_transfer(self.order.order_id, self.key, requested_by=self.customer)

		with self.assertRaises(InvalidDataError) as raised:
			self._accept(token)

		# The cancel deleted the record that carried the digest and nothing
		# replaced it: the replay is the missing-pending refusal, not a
		# credential match (upstream: accept requires a pending change).
		self.assertEqual(raised.exception.status_code, 400)
		self.assertEqual(self._record(), {})
		self.assertIsNone(self._reference_row()["owner_customer"])

	def test_a_superseded_token_is_just_a_wrong_token_while_a_request_is_live(self) -> None:
		first = self._request()
		pending = self._transfer()
		frappe.db.set_value(
			"Ceto Order Transfer", pending.name, "expires_at", add_to_date(now_datetime(), days=-1)
		)
		second = self._request()
		self.assertNotEqual(second, first)

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(first)

		# The supersession deleted the record that carried the first digest:
		# against the fresh live request the old token is a wrong credential.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertIsNone(self._reference_row()["owner_customer"])
		self._accept(second)
		self.assertEqual(self._reference_row()["owner_customer"], self.customer)

	def test_a_foreign_order_token_is_not_allowed_here(self) -> None:
		token = self._request()
		other = self._make_order_reference()
		foreign = self._request(order_id=other.order_id)

		with self.assertRaises(NotAllowedError) as raised:
			self._accept(foreign)

		# The scan is keyed on the path order's reference: another order's
		# credential is just a wrong token here, and consumes nothing.
		self.assertEqual(raised.exception.status_code, 403)
		self.assertEqual(raised.exception.message, "Invalid token.")
		self.assertIsNone(self._reference_row()["owner_customer"])

		response = self._accept(token)
		self.assertEqual(response["customer_id"], self.customer)

	def test_a_wrong_token_after_acceptance_is_invalid_data(self) -> None:
		token = self._request()
		self._accept(token)

		with self.assertRaises(InvalidDataError) as raised:
			self._accept(str(uuid.uuid4()))

		# Upstream: after accept no pending transfer remains, so a further
		# accept is invalid_data — only the consumed token itself still
		# matches a terminal record and gets not_allowed.
		self.assertEqual(raised.exception.status_code, 400)

	def test_an_unknown_order_is_masked_as_not_found(self) -> None:
		token = self._request()

		with self.assertRaises(RouteNotFoundError) as raised:
			self._accept(token, order_id=f"order_{uuid.uuid4().hex}")

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_a_wrong_scoped_key_masks_the_order_as_not_found(self) -> None:
		token = self._request()
		foreign = CartPublishableKey(region_id="reg_elsewhere", sales_channel_id="sc_elsewhere")

		with self.assertRaises(RouteNotFoundError) as raised:
			self._accept(token, key=foreign)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_a_cancelled_order_is_masked_as_not_found(self) -> None:
		token = self._request()
		frappe.db.set_value("Sales Order", self.order.sales_order, "docstatus", 2)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._accept(token)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		token = self._request()
		frappe.db.set_value(
			"Ceto Order Reference", self.order.name, "sales_order", f"SO-{uuid.uuid4().hex[:8]}"
		)

		with self.assertRaises(RouteNotFoundError) as raised:
			self._accept(token)

		self.assertEqual(raised.exception.status_code, 404)
		self.assertIsNotNone(self._transfer())

	def test_accept_never_touches_the_cart_or_sales_order(self) -> None:
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

		self._accept(token)

		# Acceptance writes the order reference only (Recorded Decision 12):
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

	def test_the_accepted_hook_receives_exactly_the_safe_payload(self) -> None:
		token = self._request()
		pending = self._transfer()

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [accepted_hook_path()]}):
			self._accept(token)

		self.assertEqual(len(ACCEPTED_HOOK_CALLS), 1)
		payload = ACCEPTED_HOOK_CALLS[0]
		self.assertEqual(set(payload), {"order_id", "transfer_id", "owner_customer", "email"})
		self.assertEqual(payload["order_id"], self.order.order_id)
		self.assertEqual(payload["transfer_id"], pending.transfer_id)
		self.assertEqual(payload["owner_customer"], self.customer)
		self.assertIsNone(payload["email"])

	def test_the_accepted_payload_carries_the_recorded_address(self) -> None:
		token = self._request(update_order_email=True)

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [accepted_hook_path()]}):
			self._accept(token)

		self.assertEqual(ACCEPTED_HOOK_CALLS[0]["email"], self.email)

	def test_the_accepted_hook_never_carries_token_material(self) -> None:
		token = self._request()
		digest = hashlib.sha256(token.encode()).hexdigest()

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [accepted_hook_path()]}):
			self._accept(token)

		# The deliberate safe payload: neither the plaintext token nor its
		# digest ever reaches a receiver (Recorded Decision 10).
		rendered = json.dumps(ACCEPTED_HOOK_CALLS)
		self.assertNotIn(token, rendered)
		self.assertNotIn(digest, rendered)

	def test_the_hook_fires_inside_the_transaction_after_the_writes(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [accepted_with_owner_hook_path()]}):
			self._accept(token)

		# The receiver already sees the moved ownership: the announcement
		# rides the same open transaction, after both writes.
		self.assertEqual(ACCEPTED_HOOK_CALLS[0]["owner_at_delivery"], self.customer)

	def test_without_a_receiver_the_acceptance_still_completes(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: []}):
			self._accept(token)

		self.assertEqual(self._reference_row()["owner_customer"], self.customer)
		self.assertEqual(self._record().status, "Accepted")

	def test_a_failing_receiver_fails_the_accept_and_rolls_the_writes_back(self) -> None:
		token = self._request()

		with self.patch_hooks({TRANSFER_ACCEPTED_HOOK: [failing_accepted_hook_path()]}):
			with self.assertRaises(RuntimeError):
				self._accept(token)

		# The receiver had already seen both writes applied inside the open
		# transaction when it failed.
		self.assertEqual(ACCEPTED_HOOK_CALLS[0]["owner_at_delivery"], self.customer)

		# The API layer's error rollback erases the whole acceptance: the
		# closed record and the moved ownership alike — no half-accepted
		# state survives (the committed fixture is what stays).
		frappe.db.rollback()
		self.assertEqual(frappe.db.count("Ceto Order Transfer", {"order_reference": self.order.name}), 0)
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", self.order.name, "owner_customer"))
