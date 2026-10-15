"""The narrow privileged boundary between Ceto payments and paygi.

Ceto never touches a gateway: the store routes resolve a provider in
Ceto's own registry (``ceto.services.payments.providers``), and exactly
one function in this module — :func:`create_payment` — is allowed to call
paygi's ``create_payment`` API. The boundary is deliberately narrow:

- **One paygi call.** ``paygi.api.create_payment`` is imported lazily at
  call time (a site without paygi installed fails the lookup, which the
  stable wrapper reports as "no charge"), never at import time, so the
  paygi app stays optional for every non-payment Ceto surface.
- **Authorization happens outside.** paygi requires a signed-in user with
  read access to the reference document, while checkout runs as Guest;
  the wrapper alone elevates to the trusted persistence scope
  (:func:`ceto.services.common.privileged_scope`), and only after the
  caller has already enforced the publishable key, the cart scope and the
  cart ownership. The elevation covers nothing but the paygi call.
- **Precise minor units.** paygi takes integer ``amount_minor`` in the
  currency's smallest unit; the conversion is exact ``Decimal`` math over
  ERPNext's ``Currency.fraction_units`` master (satang for THB, fils for
  KWD, …) — never float multiplication. An ambiguous conversion (missing
  or zero divisor, negative amount) refuses the charge instead of paying
  a wrong amount.
- **Idempotent by session.** The paygi idempotency key *is* the Ceto
  session id (``payses_…``): repeating a session-creation request finds
  the same paygi attempt instead of charging twice, and the attempt names
  its session as reference so the success webhook can find its way back.
- **Stable failure.** Provider absence and provider failure are ordinary
  outcomes, never an accidental 500: the wrapper answers ``None`` and
  logs, and the session stays ``pending`` with no provider data — the
  client retries, and a retry books a fresh attempt rather than raising.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import frappe
from frappe.utils import flt

from ceto.services.common import privileged_scope

#: The doctype/name pair every cart payment attempt references: the
#: reference is how paygi's success webhook finds the Ceto session it
#: belongs to (``ceto.services.payments.synchronization``).
REFERENCE_DOCTYPE = "Ceto Payment Session"

#: Fallback minor-unit divisor when the Currency master carries no
#: ``fraction_units`` — the overwhelmingly common two-decimal case.
DEFAULT_FRACTION_UNITS = 100


@dataclass(frozen=True)
class ProviderChargeRequest:
	"""One provider charge a session creation asks the wrapper for.

	``gateway`` is paygi's own provider name resolved from the Ceto
	provider id (``pp_beam_beam`` → ``beam``); ``amount`` / ``currency_code``
	are the session's major-unit payable snapshot; ``data`` is the client's
	optional provider payload, forwarded as paygi's PCI-safe
	``payment_method`` mapping.
	"""

	session_id: str
	gateway: str
	amount: float
	currency_code: str
	data: Mapping[str, Any] | None = None


def to_minor_units(amount: float, currency_code: str) -> int:
	"""Convert a major-unit ``amount`` to exact minor units for ``currency``.

	The divisor is ERPNext's ``Currency.fraction_units`` for the currency
	(the site's own answer to "what is the smallest unit"), defaulted to
	100 when the master leaves it unset. The amount is made exact through
	its string form and must survive the conversion without rounding — a
	value with more decimals than the currency has minor units, or a
	non-positive / non-finite amount, raises ``ValueError`` so no charge is
	ever created from an ambiguous number.
	"""
	divisor = _fraction_units(currency_code)
	if divisor <= 0:
		raise ValueError(f"Currency has no minor unit divisor: {currency_code}")
	try:
		major = Decimal(str(flt(amount)))
		if not major.is_finite():
			raise ValueError(f"Amount is not a finite number: {amount}")
		minor = (major * divisor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
	except (ArithmeticError, InvalidOperation) as error:
		raise ValueError(f"Amount does not convert to minor units: {amount}") from error
	if minor <= 0:
		raise ValueError(f"Amount is not positive in minor units: {amount} {currency_code}")
	if minor != major * divisor:
		raise ValueError(f"Amount exceeds the currency's minor unit precision: {amount} {currency_code}")
	return int(minor)


def gateway_for(provider_id: str) -> str:
	"""Resolve paygi's gateway name from a pinned ``pp_<gateway>_<gateway>`` id."""
	body = provider_id.removeprefix("pp_")
	gateway, _, _tail = body.rpartition("_")
	return gateway or body


def create_payment(request: ProviderChargeRequest) -> "dict[str, Any] | None":
	"""Create the paygi attempt for ``request``, or ``None`` on any failure.

	The whole call — conversion, elevation, paygi API — is wrapped so a
	missing paygi app, a misconfigured gateway or a transient provider
	fault all collapse into the same stable "no charge" answer, logged once
	for operators. Callers must treat ``None`` as *provider unavailable*:
	the session stays pending and no provider data exists.
	"""
	try:
		return _create_payment(request)
	except Exception:
		frappe.log_error(
			title="Ceto payment provider charge failed",
			message=f"{request.gateway} session {request.session_id}: provider unavailable",
		)
		return None


def _create_payment(request: ProviderChargeRequest) -> "dict[str, Any] | None":
	"""The trusted paygi call behind the stable wrapper."""
	# paygi is an optional app: resolve its API lazily so absence is a
	# stable failure here instead of an import-time Ceto crash.
	from paygi.api import create_payment as paygi_create_payment

	amount_minor = to_minor_units(request.amount, request.currency_code)
	with privileged_scope():
		return paygi_create_payment(
			provider=request.gateway,
			reference_doctype=REFERENCE_DOCTYPE,
			reference_name=request.session_id,
			amount_minor=amount_minor,
			currency=request.currency_code,
			idempotency_key=request.session_id,
			payment_method=dict(request.data) if request.data else None,
		)


def _fraction_units(currency_code: str) -> int:
	"""Return the currency master's minor-unit divisor, defensively."""
	units = frappe.db.get_value("Currency", (currency_code or "").upper(), "fraction_units")
	return int(flt(units)) if units else DEFAULT_FRACTION_UNITS
