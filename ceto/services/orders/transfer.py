"""Pending ownership-transfer requests (the Medusa ``requestTransfer`` surface).

An authenticated customer asks for ownership of a **guest** order: the
pinned request body carries no recipient identifier, so the pending
transfer records that requesting customer and the single-use token
travels to the order's current email for the holder's consent — accept or
decline belong to later phases (orders field-mapping Recorded Decision 9).
One request mints the whole pending state:

- **One lock, then every check**: the ``Ceto Order Reference`` row is
  locked ``FOR UPDATE`` before scope, eligibility and the pending-transfer
  scan read any state, so a concurrent request serializes on the lock and
  sees the winner's outcome instead of minting a second live request.
- **Masked resolution**: resolution is delegated to :class:`OrderAccess`,
  so an unknown id, broken lineage, a cancelled Sales Order and a
  wrong-scoped publishable key are all the same ``404 not_found`` as on
  retrieve (Recorded Decision 5) — a foreign order simply does not exist.
- **Guest-only eligibility** (Recorded Decision 9): only an order with no
  effective owner — the ``owner_customer`` snapshot, or its legacy cart
  fallback — is transferable. Any owned order is refused as ``400
  invalid_data``: deliberately stricter than upstream, which refuses only
  self-ownership, to keep the transfer a guest-order recovery flow.
- **One live pending request per order**: a request while another live one
  is pending is refused as ``400 invalid_data`` — a refusal, not an
  idempotent no-op, because the newer payload's description and
  ``update_order_email`` must never be silently dropped. An **expired**
  pending request is removed under the same lock and a fresh one is minted
  (Recorded Decision 11: expiry frees the order), exactly like the
  requester's cancel removes its record — a replayed superseded token then
  fails closed as a missing pending request, the same family as cancel.
- **Digest-only tokens** (Recorded Decision 10): the plaintext UUIDv4
  token exists only inside this request — it is handed once to the
  ``ceto_order_transfer_requested`` hook for delivery and then discarded.
  Only its SHA-256 digest is persisted (the credit wallet's ``code_hash``
  discipline); no plaintext token is ever stored, logged or returned.
- **Explicit window** (Recorded Decision 11): ``expires_at`` is stored as
  now plus ``ORDER_TRANSFER_LIFETIME_DAYS`` instead of being derived from
  creation, so the pinned lifetime is explicit and auditable.
- **Read-only lineage** (Recorded Decision 12): the order reference, the
  completed cart's reference and the Sales Order are only ever read —
  acceptance owns those writes, in its own phase.

The requester identity and email arrive from the HTTP adapter (the
authenticated session user's Customer and its email); the service accepts
no client-supplied recipient. The response is the unchanged serialized
``StoreOrder``, exactly as upstream answers — never the token.
"""

import uuid
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.credits import hash_code
from ceto.services.orders.access import OrderAccess, PublishableKeyScope
from ceto.services.orders.ownership import OrderOwnership
from ceto.services.orders.serialization import OrderSerializer
from ceto.types.http.store.orders.manifest import ORDER_TRANSFER_LIFETIME_DAYS

if TYPE_CHECKING:
	from frappe.types import _dict

#: Frappe hook through which the site delivers the transfer token (order id,
#: token, email). With no receiver registered the request stays pending until
#: its requester cancels it or it expires.
TRANSFER_REQUESTED_HOOK = "ceto_order_transfer_requested"

ORDER_NOT_TRANSFERABLE = "Only orders without an owner can be requested for transfer"
ORDER_TRANSFER_PENDING = "A transfer request is already pending for this order"


class OrderTransfer:
	"""Mint pending ownership-transfer requests for placed orders."""

	def __init__(
		self,
		access: OrderAccess | None = None,
		orders: OrderSerializer | None = None,
	) -> None:
		self.access = access or OrderAccess()
		self.orders = orders or OrderSerializer()

	def request(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		requested_by: str,
		requester_email: str | None = None,
		description: str | None = None,
		update_order_email: bool | None = None,
	) -> dict[str, Any]:
		"""Create the pending transfer of ``order_id`` for ``requested_by``.

		``key`` is the publishable key scope every Store route resolves
		(``CartPublishableKey.from_request``); ``requested_by`` is the
		authenticated caller's Customer and ``requester_email`` its email —
		both resolved by the adapter, never accepted from the payload.
		``description`` is the pinned optional request text, and
		``update_order_email`` marks acceptance to move the order's email to
		``requester_email``. Returns the unchanged serialized ``StoreOrder``;
		the token reaches only the ``ceto_order_transfer_requested`` hook.
		"""
		self._lock_reference(order_id)
		order_reference, sales_order, reference = self.access.resolve(order_id, key)
		if OrderOwnership.effective_owner(order_reference):
			raise InvalidDataError(ORDER_NOT_TRANSFERABLE)
		self._remove_expired_request(order_reference.name)

		original_email = sales_order.contact_email or None
		token = str(uuid.uuid4())
		frappe.get_doc(
			{
				"doctype": "Ceto Order Transfer",
				"transfer_id": f"tr_{uuid.uuid4().hex}",
				"status": "Pending",
				"order_reference": order_reference.name,
				"requested_by": requested_by,
				"description": description or None,
				"token_hash": hash_code(token),
				"expires_at": add_to_date(now_datetime(), days=ORDER_TRANSFER_LIFETIME_DAYS),
				"original_email": original_email,
				"new_email": requester_email if update_order_email else None,
			}
		).insert(ignore_permissions=True)
		self._notify_requested(order_reference.order_id, token, original_email)
		return self.orders.serialize(order_reference, sales_order, reference)

	@staticmethod
	def _lock_reference(order_id: str) -> None:
		"""Row-lock the order reference before any check reads state.

		Every check below — access scope, eligibility, the pending scan and
		the insert — runs inside this lock, so a concurrent request for the
		same order serializes after the winner and sees its outcome. An
		unknown id locks nothing and is masked by the access gate.
		"""
		table = frappe.qb.DocType("Ceto Order Reference")
		frappe.qb.from_(table).select(table.name).where(table.name == order_id).for_update().run()

	@classmethod
	def _remove_expired_request(cls, order_reference: str) -> None:
		"""Free the order from an expired request under the held lock.

		A live pending request refuses a second one — the newer payload's
		description and ``update_order_email`` must not be silently dropped.
		An expired one is removed like the requester's cancel removes its
		record, and the caller mints a fresh request in its place; the
		superseded token dies with the record and any replay of it fails
		closed as a missing pending request.
		"""
		live = None
		for record in cls._pending_requests(order_reference):
			if get_datetime(record.expires_at) <= now_datetime():
				frappe.delete_doc("Ceto Order Transfer", record.name, ignore_permissions=True)
			else:
				live = record
		if live:
			raise InvalidDataError(ORDER_TRANSFER_PENDING)

	@staticmethod
	def _pending_requests(order_reference: str) -> "list[_dict]":
		"""The order's pending transfer records, if any."""
		return frappe.get_all(
			"Ceto Order Transfer",
			filters={"order_reference": order_reference, "status": "Pending"},
			fields=["name", "expires_at"],
		)

	@staticmethod
	def _notify_requested(order_id: str, token: str, email: str | None) -> None:
		"""Hand the plaintext token once to the delivery hook.

		Every registered receiver runs inside the request's open
		transaction: a receiver failure propagates, so the API layer's
		rollback removes the just-inserted request instead of leaving a
		token whose delivery failed. With no receiver registered the
		request simply stays pending until its requester cancels it or it
		expires.
		"""
		for method in frappe.get_hooks(TRANSFER_REQUESTED_HOOK, []):
			# Hook paths come exclusively from installed-app configuration. This is the
			# standard Frappe extension boundary, not request-controlled dynamic code.
			frappe.call(  # nosemgrep: frappe-codeinjection-eval
				frappe.get_attr(method),
				order_id=order_id,
				token=token,
				email=email,
			)
