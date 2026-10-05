import re

import frappe
from frappe import _
from frappe.model.document import Document

_TRANSFER_ID_PATTERN = re.compile(r"tr_[0-9a-f]{32}")
_TOKEN_HASH_PATTERN = re.compile(r"[0-9a-f]{64}")


class CetoOrderTransfer(Document):
	"""A pending ownership transfer of a placed order.

	One record per transfer request (orders field-mapping, Recorded Decisions
	9-12): the requesting customer seeks ownership of a guest/unowned order
	for themselves, the token travels to the order's current email, and
	acceptance applies ownership to the customer recorded here — never to a
	payload-supplied or email-guessed recipient. The record is named by the
	public ``transfer_id`` (``tr_`` + 32 lowercase hex, the minted shape of
	``ceto.services`` id helpers).

	The single-use token is stored digest-only — a SHA-256 hex digest, the
	same hash-only discipline as the credit wallet's ``code_hash`` — because
	upstream persists the plaintext token on its order change and Ceto
	deliberately hardens beyond that: the plaintext exists only inside the
	request that mints it, is handed once to the
	``ceto_order_transfer_requested`` hook for delivery, and is never stored,
	logged or returned. The digest is unique as well as indexed, so an
	accidental digest reuse fails closed at insert instead of two records
	ever sharing one credential. ``expires_at`` stores the pinned 7-day
	window (Recorded Decision 11): the lifetime could be derived from
	creation, but the minting request persists its computed expiry so the
	window stays explicit and auditable — enforcing it is the service's
	fail-closed check, not a record invariant, so a record whose window has
	passed stays addressable for that refusal and for the requester's
	cancel. ``description`` retains the pinned optional
	``StoreRequestOrderTransfer`` description verbatim, so the accepted
	request field is auditable rather than silently discarded.
	``original_email`` snapshots the recipient address at
	request time; ``new_email`` is set only when ``update_order_email`` was
	requested, and its presence is the flag acceptance applies.

	Deliberately *not* pinned by this schema: one active transfer per order
	is the transfer service's locked invariant (a concurrent request
	serializes on the service lock and loses), not a unique constraint on
	``order_reference`` — a constraint could not express that cancel removes
	the record and expiry frees the order for a fresh request, and terminal
	records must remain addressable beside a new pending one. Guest-order
	eligibility is likewise a request-time refusal of the service, not a
	record invariant.
	"""

	def validate(self) -> None:
		self._validate_transfer_id()
		self._validate_token_hash()
		self._validate_emails()
		self._validate_lifecycle()

	def _validate_transfer_id(self) -> None:
		"""Pin the public id to its minted shape; an id is never normalized."""
		if not _TRANSFER_ID_PATTERN.fullmatch(self.transfer_id or ""):
			frappe.throw(_("Transfer ID must be 'tr_' followed by 32 lowercase hex characters"))

	def _validate_token_hash(self) -> None:
		"""Normalize the digest, then pin it to lowercase SHA-256 hex.

		The digest is the only credential material the record ever carries,
		so it is validated strictly after normalization: whitespace is
		stripped, case is folded to lowercase, and anything that is not a
		64-character lowercase hex string is refused — a digest is compared
		exactly, and a malformed one must fail loudly instead of silently
		never matching.
		"""
		self.token_hash = (self.token_hash or "").strip().lower()
		if not _TOKEN_HASH_PATTERN.fullmatch(self.token_hash):
			frappe.throw(_("Token hash must be a 64-character lowercase SHA-256 hex digest"))

	def _validate_emails(self) -> None:
		"""The optional email columns are addresses, never free text with padding."""
		for fieldname in ("original_email", "new_email"):
			value = self.get(fieldname)
			if value is not None:
				self.set(fieldname, value.strip() or None)

	def _validate_lifecycle(self) -> None:
		"""A transfer is born Pending; once Accepted or Declined it is terminal.

		The lifecycle is terminal by contract: after accept, decline or
		cancel no pending transfer remains, so a terminal record never moves
		on — replaying a consumed token is the service's ``not_allowed``
		refusal, and this guard is the backstop that keeps a stale or
		hand-written update from resurrecting one.
		"""
		if self.is_new():
			if self.status != "Pending":
				frappe.throw(_("A new transfer must start out Pending"))
			return
		previous = frappe.db.get_value("Ceto Order Transfer", self.name, "status")
		if previous in ("Accepted", "Declined") and self.status != previous:
			frappe.throw(_("A {0} transfer is terminal and cannot change status").format(previous))
