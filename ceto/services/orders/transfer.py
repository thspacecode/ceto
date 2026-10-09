"""The ownership-transfer lifecycle of placed orders: the Medusa
``requestTransfer``, ``acceptTransfer`` and ``cancelTransfer`` surfaces.

An authenticated customer asks for ownership of a **guest** order: the
pinned request body carries no recipient identifier, so the pending
transfer records that requesting customer and the single-use token
travels to the order's current email for the holder's consent (orders
field-mapping Recorded Decision 9).
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
  acceptance owns those writes.

**Accept** is the holder's consent (the ``acceptTransfer`` surface): the
presented token is hashed and its digest matched against this path
order's records only — a token minted for another order is just a wrong
credential here. Under the same lock, every failing credential is
refused without mutation: a wrong token, a token past its window and a
replayed consumed or declined token (the terminal record still carries
the digest) are all the same ``403 not_allowed`` ``Invalid token.`` —
expired credentials are indistinguishable from wrong ones — while a
digest that matches no record of the order is a wrong credential for as
long as a live pending request exists and becomes the ``400
invalid_data`` missing-pending refusal once none does: never minted, or
the request that carried the digest was cancelled or expiry-superseded
away (its deletion is the credential's death; Recorded Decision 11). A
matching live pending transfer is consumed atomically: the order reference's
``owner_customer`` becomes the stored ``requested_by`` (optionally the
reference's ``email`` the stored ``new_email``) and the record closes as
``Accepted`` — never the cart reference, never the Sales Order (Recorded
Decision 12).

**Decline** is the holder's refusal (the ``declineTransfer`` surface): the
same lock, masked resolution and credential gates as accept — the token is
only ever hashed and every failing credential is refused exactly as there —
but the holder's answer is one write: the record closes as ``Declined``.
Ownership stays as it was, and the order reference's email and ``modified``
stamp, the cart reference and the Sales Order are untouched (Recorded
Decision 12), leaving the still-guest order free for a fresh request. The
``ceto_order_transfer_declined`` hook announces the refusal inside the
transaction with the same safe payload shape as acceptance, never any token
material.

**Cancel** is the requester's removal of that pending state (the Medusa
``cancelTransfer`` surface): the same lock-then-mask order finds the order
reference, and the pending record is matched regardless of ``expires_at``
— an expired request stays cancellable by its requester (Recorded
Decision 11). Deleting the record destroys the digest-only token with it,
so cancellation is the record's death, never a status flip. A missing
pending request, including a replayed cancel, is ``400 invalid_data``; any
caller other than the recorded ``requested_by`` is ``403 not_allowed`` and
consumes nothing.

The requester identity and email arrive from the HTTP adapter (the
authenticated session user's Customer and its email); the service accepts
no client-supplied recipient. The response is the unchanged serialized
``StoreOrder``, exactly as upstream answers — never the token.
"""

import uuid
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from ceto.routing.exceptions import InvalidDataError, NotAllowedError
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

#: Frappe hook announcing a consumed transfer (order id, transfer id, owner
#: customer, recorded email). Fired inside the accepting transaction; the
#: payload never carries token material.
TRANSFER_ACCEPTED_HOOK = "ceto_order_transfer_accepted"

#: Frappe hook announcing a refused transfer (order id, transfer id, requester
#: customer, would-be email). Fired inside the declining transaction; the
#: payload never carries token material.
TRANSFER_DECLINED_HOOK = "ceto_order_transfer_declined"

ORDER_NOT_TRANSFERABLE = "Only orders without an owner can be requested for transfer"
ORDER_TRANSFER_PENDING = "A transfer request is already pending for this order"
ORDER_TRANSFER_NOT_PENDING = "No pending transfer request exists for this order"
#: The one refusal every failing credential gets (upstream's pinned message):
#: wrong, expired and replayed consumed/declined tokens are indistinguishable.
ORDER_TRANSFER_INVALID_TOKEN = "Invalid token."
ORDER_TRANSFER_CANCEL_FORBIDDEN = "Only the customer who requested the transfer can cancel it"


def _dispatch_hook(hook: str, **payload: "str | None") -> None:
	"""Run every registered receiver of an order-transfer hook.

	Hook paths come exclusively from installed-app configuration. This is
	the standard Frappe extension boundary, not request-controlled dynamic
	code. Every receiver runs inside the caller's open transaction.
	"""
	for method in frappe.get_hooks(hook, []):
		frappe.call(  # nosemgrep: frappe-codeinjection-eval
			frappe.get_attr(method),
			**payload,
		)


class OrderTransfer:
	"""Mint, accept, decline and cancel pending ownership-transfer requests for placed orders."""

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

	def accept(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		token: str,
	) -> dict[str, Any]:
		"""Consume the pending transfer of ``order_id`` with its single-use ``token``.

		The order reference is row-locked before any check and resolution is
		the retrieve path's masked ``404 not_found``. The token is only ever
		hashed: the digest is matched against this path order's records, and
		every failing credential — wrong, expired, replayed-accepted,
		declined — is the same ``403 not_allowed`` ``Invalid token.``
		without mutation, while a digest matching no record of an order
		without a live pending request is the ``400 invalid_data``
		missing-pending refusal. The winner is consumed atomically: the
		order reference's ``owner_customer`` is set to the transfer's
		stored ``requested_by`` (optionally the reference's ``email`` to
		the stored ``new_email``, the ``update_order_email`` target) and
		the record closes as ``Accepted`` — the cart reference and the
		Sales Order are never written (Recorded Decision 12). The
		``ceto_order_transfer_accepted`` hook announces the consumed
		transfer inside the transaction without any token material. The
		response is the reloaded, re-serialized ``StoreOrder`` — never the
		token.
		"""
		self._lock_reference(order_id)
		order_reference, sales_order, reference = self.access.resolve(order_id, key)
		transfer = self._acceptable_transfer(order_reference.name, hash_code(token))
		# One UPDATE: the owner snapshot and the optional recorded address
		# move together, or a failure's rollback takes both back (Recorded
		# Decisions 2 and 12).
		values: dict[str, str] = {"owner_customer": transfer.requested_by}
		if transfer.new_email:
			values["email"] = transfer.new_email
		frappe.db.set_value("Ceto Order Reference", order_reference.name, values)
		frappe.db.set_value("Ceto Order Transfer", transfer.name, "status", "Accepted")
		self._notify_accepted(
			order_id=order_reference.order_id,
			transfer_id=transfer.transfer_id,
			owner_customer=transfer.requested_by,
			email=values.get("email"),
		)
		order_reference.reload()
		return self.orders.serialize(order_reference, sales_order, reference)

	def decline(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		token: str,
	) -> dict[str, Any]:
		"""Refuse the pending transfer of ``order_id`` with its single-use ``token``.

		The same lock, masked resolution and credential gates as
		:meth:`accept` apply — the order reference is row-locked before any
		check, the token is only ever hashed, and every failing credential —
		wrong, expired, replayed-accepted, replayed-declined — is the same
		``403 not_allowed`` ``Invalid token.`` without mutation, while a
		digest matching no record of an order without a live pending request
		is the ``400 invalid_data`` missing-pending refusal. The holder's
		refusal is one write: the record closes as ``Declined`` — ownership
		stays as it was, and the order reference's email and ``modified``
		stamp, the cart reference and the Sales Order are untouched
		(Recorded Decision 12), leaving the still-guest order free for a
		fresh request. The ``ceto_order_transfer_declined`` hook announces
		the refusal inside the transaction with the same safe payload shape
		as acceptance and never any token material. The response is the
		unchanged serialized ``StoreOrder`` — never the token.
		"""
		self._lock_reference(order_id)
		order_reference, sales_order, reference = self.access.resolve(order_id, key)
		transfer = self._acceptable_transfer(order_reference.name, hash_code(token))
		frappe.db.set_value("Ceto Order Transfer", transfer.name, "status", "Declined")
		self._notify_declined(
			order_id=order_reference.order_id,
			transfer_id=transfer.transfer_id,
			owner_customer=transfer.requested_by,
			email=transfer.new_email,
		)
		return self.orders.serialize(order_reference, sales_order, reference)

	def cancel(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		requested_by: str,
	) -> dict[str, Any]:
		"""Remove the pending transfer of ``order_id`` requested by ``requested_by``.

		``key`` is the publishable key scope every Store route resolves
		(``CartPublishableKey.from_request``); ``requested_by`` is the
		authenticated caller's Customer, resolved by the adapter — never
		accepted from the payload. The pending record is found regardless of
		``expires_at`` (Recorded Decision 11: the requester can still cancel
		an expired request) and deleting it destroys the digest-only token
		with the record. The order reference, its completed cart and the
		Sales Order are never written (Recorded Decision 12); the response
		is the unchanged serialized ``StoreOrder`` — never the token.
		"""
		self._lock_reference(order_id)
		order_reference, sales_order, reference = self.access.resolve(order_id, key)
		pending = self._pending_requests(order_reference.name)
		if not pending:
			raise InvalidDataError(ORDER_TRANSFER_NOT_PENDING)
		if pending[0].requested_by != requested_by:
			raise NotAllowedError(ORDER_TRANSFER_CANCEL_FORBIDDEN)
		frappe.delete_doc("Ceto Order Transfer", pending[0].name, ignore_permissions=True)
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

	@classmethod
	def _acceptable_transfer(cls, order_reference: str, digest: str) -> "_dict":
		"""Return the live pending transfer ``digest`` unlocks, or refuse.

		Every check runs under the held reference lock and keyed on this
		path order's reference alone, so a token minted for another order
		cannot match here — against this order it is just a wrong or
		missing credential. The order is pinned:

		- A pending record matching the digest is the candidate; past its
		  window it gets the same ``not_allowed`` as any other failing
		  credential — expired tokens are indistinguishable from wrong
		  ones and mutate nothing (Recorded Decision 11).
		- A terminal record still matching the digest is a consumed or
		  declined credential: the same ``not_allowed``, checked before
		  the missing-pending fallback so a replayed accept or
		  re-presented declined token can never be told apart from a
		  wrong guess.
		- A live pending request under a different token is a wrong token.
		- No matching digest and no live pending request is the
		  ``invalid_data`` missing-pending refusal — never minted,
		  cancelled, or superseded after expiry; all three deleted the
		  record that carried the digest.
		"""
		pending = cls._pending_requests(order_reference)
		for record in pending:
			if record.token_hash == digest:
				if get_datetime(record.expires_at) <= now_datetime():
					raise NotAllowedError(ORDER_TRANSFER_INVALID_TOKEN)
				return record
		if digest in cls._terminal_hashes(order_reference):
			raise NotAllowedError(ORDER_TRANSFER_INVALID_TOKEN)
		if pending:
			raise NotAllowedError(ORDER_TRANSFER_INVALID_TOKEN)
		raise InvalidDataError(ORDER_TRANSFER_NOT_PENDING)

	@staticmethod
	def _terminal_hashes(order_reference: str) -> "list[str]":
		"""The digests the order's closed transfers still carry.

		Terminal records stay addressable beside a new pending one (the
		record schema pins no per-order uniqueness), so a replayed
		accepted or declined credential still finds its digest here and
		fails closed as ``not_allowed`` instead of the missing-pending
		``invalid_data`` that cancelled and superseded records — deleted
		with their digest — produce.
		"""
		return frappe.get_all(
			"Ceto Order Transfer",
			filters={
				"order_reference": order_reference,
				"status": ("in", ("Accepted", "Declined")),
			},
			pluck="token_hash",
		)

	@staticmethod
	def _pending_requests(order_reference: str) -> "list[_dict]":
		"""The order's pending transfer records, if any, regardless of expiry.

		Expiry is deliberately the caller's concern: :meth:`request`
		removes the expired records under the lock before minting a fresh
		one, :meth:`cancel` must still find an expired record — the
		requester's cancel is exactly what removes it (Recorded Decision
		11) — and :meth:`accept` compares the presented digest and reads
		the stored requester and email from the winner.
		"""
		return frappe.get_all(
			"Ceto Order Transfer",
			filters={"order_reference": order_reference, "status": "Pending"},
			fields=["name", "transfer_id", "token_hash", "expires_at", "requested_by", "new_email"],
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
		_dispatch_hook(TRANSFER_REQUESTED_HOOK, order_id=order_id, token=token, email=email)

	@staticmethod
	def _notify_accepted(
		*,
		order_id: str,
		transfer_id: str,
		owner_customer: str,
		email: str | None,
	) -> None:
		"""Announce the consumed transfer through the completion hook.

		Fires inside the accepting transaction, after both writes: a
		receiver already sees the moved ownership, and a receiver failure
		propagates, so the API layer's rollback takes the acceptance back
		whole. The payload is deliberately safe and exactly
		``(order_id, transfer_id, owner_customer, email)`` — the public
		order id, the public ``tr_…`` transfer id, the Customer that now
		owns the order (the transfer's stored requester) and the address
		recorded on the order reference (``None`` without
		``update_order_email``): the identifiers a site integration needs
		to tell the recipient the transfer completed. No token material
		ever rides it — the credential is consumed, and neither the
		plaintext nor its digest is handed out again.
		"""
		_dispatch_hook(
			TRANSFER_ACCEPTED_HOOK,
			order_id=order_id,
			transfer_id=transfer_id,
			owner_customer=owner_customer,
			email=email,
		)

	@staticmethod
	def _notify_declined(
		*,
		order_id: str,
		transfer_id: str,
		owner_customer: str,
		email: str | None,
	) -> None:
		"""Announce the refused transfer through the completion hook.

		Fires inside the declining transaction, after the status write: a
		receiver already sees the record closed ``Declined``, and a receiver
		failure propagates, so the API layer's rollback takes the decline
		back whole. The payload keeps the completion shape of
		:meth:`_notify_accepted` and is deliberately safe:
		``(order_id, transfer_id, owner_customer, email)`` — the public
		order id, the public ``tr_…`` transfer id, the Customer whose
		request the decline closes (the transfer's stored requester;
		ownership never moved) and the address the declined request would
		have recorded (the stored ``new_email``, ``None`` without
		``update_order_email``): the identifiers a site integration needs to
		tell the requester the transfer was refused. No token material ever
		rides it — the credential is consumed, and neither the plaintext nor
		its digest is handed out again.
		"""
		_dispatch_hook(
			TRANSFER_DECLINED_HOOK,
			order_id=order_id,
			transfer_id=transfer_id,
			owner_customer=owner_customer,
			email=email,
		)
