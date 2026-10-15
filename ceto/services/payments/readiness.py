"""The completion payment gate behind ``ceto_cart_payment_readiness``.

Cart completion consults this hook before placing an order (registered in
``ceto/hooks.py`` under the ``PAYMENT_READINESS_HOOK`` name the completion
service pins). The verdict is the payment policy's:

- **``off`` (default)** — the hook answers ``None`` ("no opinion") without
  touching a single payment row, so completion's gate stays open and
  upgrading sites keep completing carts exactly as before.
- **``enforced``** — the hook decides, failing **closed**: a cart is
  completable only with a provable payment, which is the cart's
  collection carrying a *current* session that is ``authorized`` or
  ``captured``, still naming the cart's live payable (amount and
  currency), for a provider that still resolves and is enabled. A missing
  collection, a missing or stale session, an unpaid/failed/canceled one,
  an amount or currency mismatch and an unknown or disabled provider all
  refuse the completion — and any unexpected failure of the check itself
  refuses too, with the reason logged for operators. The gate may only
  ever be wrong in the strict direction.

The ``idempotency_key`` keyword is part of the pinned hook contract; the
verdict does not depend on it (session idempotency lives in the
collections service, capture-once in the synchronization module).
"""

import frappe
from frappe.utils import flt

from ceto.services.payments.policy import resolve_payment_policy
from ceto.services.payments.providers import default_registry

#: The only session states that prove money for completion.
PAID_SESSION_STATUSES = ("authorized", "captured")


def cart_payment_ready(
	cart_id: str,
	quotation: str,
	idempotency_key: "str | None" = None,
) -> "bool | None":
	"""Return ``None`` when payments are off, else whether payment is proven.

	``cart_id`` is the completing cart's public id, ``quotation`` its
	Quotation's name (the completion passes the row-locked pair).
	"""
	policy = resolve_payment_policy()
	if not policy.enforced:
		return None
	try:
		return _is_paid(cart_id, quotation)
	except Exception:
		_log_check_failure(cart_id)
		return False


def _log_check_failure(cart_id: str) -> None:
	"""Log the failed gate; the log write must never break the refusal."""
	try:
		frappe.log_error(
			title="Ceto payment readiness check failed",
			message=f"cart {cart_id}: failing the completion closed",
		)
	except Exception:
		pass


def _is_paid(cart_id: str, quotation_name: str) -> bool:
	"""Whether the cart holds a current, paid, payable-matching session."""
	collection = frappe.db.get_value("Ceto Payment Collection", {"cart_reference": cart_id}, "name")
	if not collection:
		return False
	session = frappe.db.get_value(
		"Ceto Payment Session",
		{"payment_collection": collection, "is_current": 1},
		["provider_id", "amount", "currency_code", "status"],
		as_dict=True,
	)
	if session is None or session.status not in PAID_SESSION_STATUSES:
		return False
	payable = frappe.db.get_value(
		"Quotation",
		quotation_name,
		["grand_total", "currency", "docstatus"],
		as_dict=True,
	)
	if payable is None or payable.docstatus != 0:
		return False
	if flt(session.amount) != flt(payable.grand_total):
		return False
	if session.currency_code != str(payable.currency or "").lower():
		return False
	provider = default_registry().resolve(session.provider_id)
	return provider is not None and provider.is_enabled()
