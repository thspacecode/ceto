"""Ceto payment provider protocol, registry and the built-in paygi adapter.

Ceto owns its provider registry; paygi stays untouched. A provider is, to
the store API, just the pinned ``StorePaymentProvider`` id — the registry
maps those ids onto installed gateway backends and answers the only two
questions the store surface may ask: *which providers exist* and *which
are enabled right now*.

The built-in adapters wrap paygi's ``Beam Settings`` and ``Stripe
Settings`` singletons. They are deliberately defensive: a site without
paygi installed (or without the settings tables) simply has no enabled
providers instead of a crash, and any failure reading a settings row is
reported as "disabled" — a payment provider must never fail a read open.
Provider ids follow Medusa's ``pp_<gateway>_<gateway>`` convention
(``pp_beam_beam``, ``pp_stripe_stripe``).
"""

from dataclasses import dataclass
from typing import Protocol

import frappe
from frappe.utils import cint


class PaymentProvider(Protocol):
	"""One payment provider backend as the registry sees it."""

	@property
	def id(self) -> str:
		"""The pinned ``StorePaymentProvider`` id (``pp_…``)."""
		...

	def is_enabled(self) -> bool:
		"""Whether the backend is installed, configured and switched on."""
		...


@dataclass(frozen=True)
class PaygiProvider:
	"""Defensive adapter over one paygi settings singleton.

	``gateway`` is paygi's own provider name (``beam`` / ``stripe``),
	``settings_doctype`` the singleton carrying the ``enabled`` switch. The
	adapter reads nothing unless the paygi app and the settings table both
	exist, and any read failure counts as disabled (fail closed, no crash).
	"""

	gateway: str
	settings_doctype: str

	@property
	def id(self) -> str:
		return f"pp_{self.gateway}_{self.gateway}"

	def is_enabled(self) -> bool:
		if "paygi" not in (frappe.get_installed_apps() or []):
			return False
		if not frappe.db.table_exists(f"tab{self.settings_doctype}"):
			return False
		return paygi_settings_enabled(self.settings_doctype)


def paygi_settings_enabled(settings_doctype: str) -> bool:
	"""Return the settings singleton's ``enabled`` switch, defensively.

	The single boundary where the paygi schema is actually read. A missing
	row or an unexpected read error is reported as disabled — never raised,
	not even when the error log itself cannot be written.
	"""
	try:
		return cint(frappe.db.get_single_value(settings_doctype, "enabled")) == 1
	except Exception:
		_log_read_failure(settings_doctype)
		return False


def _log_read_failure(settings_doctype: str) -> None:
	try:
		frappe.log_error(
			title="Ceto payment provider settings read failed",
			message=f"{settings_doctype}: unreadable paygi settings treated as disabled",
		)
	except Exception:
		# The Error Log write failing too must not turn the defensive
		# "disabled" answer into a crash.
		pass


class ProviderRegistry:
	"""The payment providers Ceto can offer, keyed by public provider id."""

	def __init__(self, providers: tuple[PaymentProvider, ...]) -> None:
		self._providers = tuple(providers)

	def providers(self) -> tuple[PaymentProvider, ...]:
		return self._providers

	def enabled(self) -> tuple[PaymentProvider, ...]:
		"""Return the providers currently enabled on this site."""
		return tuple(provider for provider in self._providers if provider.is_enabled())

	def resolve(self, provider_id: str) -> PaymentProvider | None:
		"""Return the provider registered under ``provider_id``, if any."""
		for provider in self._providers:
			if provider.id == provider_id:
				return provider
		return None


def default_registry() -> ProviderRegistry:
	"""The built-in registry: the paygi Beam and Stripe adapters."""
	return ProviderRegistry(
		(
			PaygiProvider(gateway="beam", settings_doctype="Beam Settings"),
			PaygiProvider(gateway="stripe", settings_doctype="Stripe Settings"),
		)
	)
