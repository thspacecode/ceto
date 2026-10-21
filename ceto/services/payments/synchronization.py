"""Synchronize paygi payment success onto Ceto payment sessions.

paygi owns the provider conversation: its verified webhooks flip a
``Payment Attempt`` to ``Succeeded`` and announce that through the
``paygi_payment_succeeded`` hook (registered in ``ceto/hooks.py``). This
module is Ceto's side of that handshake:

- The attempt finds its session through the reference every cart payment
  carries (``Ceto Payment Session`` / the ``payses_…`` id — see
  ``ceto.services.payments.gateway``); attempts created by any other
  integration reference something else and are ignored.
- The capture decides under row locks, not from a pre-lock snapshot: the
  caller's transaction takes the collection row lock, then the session's
  — the same order every payment-writing flow uses — and reads the
  session's state only after both. A delivery racing a session
  recreation therefore serializes against it and answers what it
  committed: a session the recreation already made stale captures as
  history only and never completes the collection, while a session the
  recreation could not have touched yet is captured with the collection.
- A succeeded attempt flips its session to the pinned ``captured`` state
  exactly once: a session already (or no longer) captureable is left
  untouched, so replays and out-of-order deliveries cannot double-apply.
- When the captured session is still the collection's current one under
  that lock, the collection completes with it (the pinned ``completed``
  state). Otherwise the collection keeps tracking its live session, and
  completion's enforced payment gate keeps refusing until *that* session
  is paid.
- The webhook takes no cart row lock. The creation flows hold the cart
  locks *before* the collection's, so acquiring the cart here — after
  the collection — would be the one ordering that can deadlock; every
  payment writer agrees on cart → collection → session instead.

The hook runs inside the caller's (paygi webhook) transaction: a failure
propagates, so the delivery is retried by the provider instead of a
succeeded payment being lost, and the caller's rollback undoes whatever
the capture already wrote. The same contract covers the race with a
session recreation: the capture's decision reads are locking reads, and
on a REPEATABLE READ database a locking read whose transaction snapshot
predates the recreation's commit answers with the deadlock-class
"record has changed" error (``frappe.QueryDeadlockError``) rather than
stale data — no capture is written, and the retried delivery decides
from the recreation's committed outcome.
"""

from typing import TYPE_CHECKING, Any

import frappe

from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.gateway import REFERENCE_DOCTYPE

if TYPE_CHECKING:
	from frappe.model.document import Document

SESSION_CAPTURED = "captured"

COLLECTION_COMPLETED = "completed"


def on_paygi_payment_succeeded(payment_attempt: "Document") -> None:
	"""The ``paygi_payment_succeeded`` hook handler.

	Attempts that reference a Ceto payment session capture it; anything
	else (other integrations sharing the gateway) is not Ceto's money and
	is ignored.
	"""
	if getattr(payment_attempt, "reference_doctype", None) != REFERENCE_DOCTYPE:
		return
	capture_session(payment_attempt.reference_name)


def capture_session(session_id: str) -> bool:
	"""Mark one session captured exactly once; complete its collection.

	Returns whether this call performed the capture. The decision is made
	from the session row re-read under the collection-then-session row
	locks, so a delivery racing a session recreation waits for the
	recreation to commit and then answers its outcome — it can never
	complete the collection from a stale session. On a REPEATABLE READ
	database the locking read answers a recreation that committed behind
	the delivery's snapshot with the deadlock-class
	``frappe.QueryDeadlockError`` (before any write), which propagates to
	the retrying provider like every capture failure. A session already
	(or no longer) captureable is left untouched, so repeated and replayed
	deliveries do nothing.
	"""
	session = frappe.db.get_value(
		"Ceto Payment Session", session_id, ["name", "payment_collection"], as_dict=True
	)
	if session is None:
		return False
	PaymentCollections.lock_collection(session.payment_collection)
	state = frappe.db.get_value(
		"Ceto Payment Session",
		session.name,
		["name", "payment_collection", "is_current", "status"],
		as_dict=True,
		for_update=True,
	)
	if state is None or state.status not in ("pending", "pending_authorization", "requires_more"):
		return False
	frappe.db.set_value("Ceto Payment Session", state.name, "status", SESSION_CAPTURED)
	if state.is_current:
		frappe.db.set_value(
			"Ceto Payment Collection", state.payment_collection, "status", COLLECTION_COMPLETED
		)
	return True


def session_for_attempt(payment_attempt: "Document") -> "str | None":
	"""Return the session id a paygi attempt was created for, if any."""
	if getattr(payment_attempt, "reference_doctype", None) != REFERENCE_DOCTYPE:
		return None
	return payment_attempt.reference_name


def attempt_status_to_session(status: "Any") -> "str | None":
	"""Map a paygi attempt's terminal status onto the session union.

	Only terminal attempt states move a session; everything else
	(``Initiated``, ``Requires Action``, ``Pending``, ``Unknown``) keeps
	the session ``pending`` — the attempt is still in flight or retryable.
	"""
	return {"Succeeded": SESSION_CAPTURED, "Failed": "error", "Canceled": "canceled"}.get(status)
