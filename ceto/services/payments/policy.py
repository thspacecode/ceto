"""Payment policy parser for the ``ceto_cart.payment_policy`` site config.

The policy decides whether a cart must hold a live payment before it can
complete:

- ``off`` (default): payments are optional — completion's existing open
  payment readiness gate stays open. This is the backward-compatible
  default, so upgrading sites keep completing carts exactly as before.
- ``enforced``: payments are required — a cart without a provable payment
  fails completion closed. Missing, unreadable or unknown configuration
  also resolves to ``enforced``: a policy must never fail open by
  accident (an operator typo may only make checkout *stricter*, never
  looser).
"""

from dataclasses import dataclass

import frappe

POLICY_OFF = "off"

POLICY_ENFORCED = "enforced"

#: The policy key inside the ``ceto_cart`` site-config section
#: (``bench set-config ceto_cart.payment_policy …``).
POLICY_CONFIG_KEY = "payment_policy"

CART_SETTINGS_SECTION = "ceto_cart"


@dataclass(frozen=True)
class PaymentPolicy:
	"""One resolved payment policy.

	``mode`` is always one of the two allowed values — the parser never
	returns an unknown mode. ``source`` records how the mode was reached
	(``default``, ``configured`` or ``fallback``) so callers and tests can
	tell a deliberate ``enforced`` from the fail-closed fallback without
	re-parsing the config.
	"""

	mode: str
	source: str = "configured"

	@property
	def enforced(self) -> bool:
		return self.mode == POLICY_ENFORCED


def resolve_payment_policy() -> PaymentPolicy:
	"""Resolve the payment policy from the site config, failing closed.

	Values are compared case-insensitively after trimming whitespace. An
	unset or blank value — or no ``ceto_cart`` section at all — is the
	backward-compatible ``off`` default; a non-mapping ``ceto_cart``
	section or an unknown value falls back to ``enforced`` so a broken
	configuration can only tighten checkout.
	"""
	settings = frappe.conf.get(CART_SETTINGS_SECTION)
	if settings is None:
		return PaymentPolicy(mode=POLICY_OFF, source="default")
	if not isinstance(settings, dict):
		return PaymentPolicy(mode=POLICY_ENFORCED, source="fallback")
	return _parse_policy(settings.get(POLICY_CONFIG_KEY))


def _parse_policy(raw) -> PaymentPolicy:
	if raw is None or not str(raw).strip():
		return PaymentPolicy(mode=POLICY_OFF, source="default")
	normalized = str(raw).strip().lower()
	if normalized == POLICY_ENFORCED:
		return PaymentPolicy(mode=POLICY_ENFORCED, source="configured")
	if normalized == POLICY_OFF:
		return PaymentPolicy(mode=POLICY_OFF, source="configured")
	return PaymentPolicy(mode=POLICY_ENFORCED, source="fallback")
