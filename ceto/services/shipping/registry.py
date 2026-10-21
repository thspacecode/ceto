"""Deterministic registry of shipping providers.

The registry fixes the option listing's two invariants: determinism and
isolation. Determinism — the built-in ERPNext provider registers first,
hook providers follow in hook declaration order, and the first provider
claiming an id wins, so the same site configuration always produces the
same registry, the same provider order and the same option order.
Isolation — a hook path that does not resolve, a registrant without the
provider shape and a provider that raises mid-listing are logged and
skipped: one broken provider can never fail an option read, it can only
contribute nothing.

Downstream apps register through the ``ceto_shipping_providers`` hook.
Each entry is a dotted path to a provider class (instantiated with no
arguments), a zero-argument factory returning an instance, or a ready
instance; paths come exclusively from installed-app hooks configuration,
never from request input.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

import frappe

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.errors import MalformedShippingOptionIdError
from ceto.services.shipping.ids import decode_option_id
from ceto.services.shipping.options import ShippingOptionQuote
from ceto.services.shipping.providers.erpnext import PROVIDER_ID, ErpnextShippingRuleProvider

SHIPPING_PROVIDERS_HOOK = "ceto_shipping_providers"

if TYPE_CHECKING:
	from ceto.services.shipping.providers.base import ShippingProvider


class ShippingProviderRegistry:
	"""Ordered, first-wins registry; quotes resolve through every provider."""

	def __init__(self, providers: Sequence["ShippingProvider"]) -> None:
		registry: dict[str, "ShippingProvider"] = {}
		for provider in providers:
			registry.setdefault(provider.id, provider)
		self._providers_by_id = registry

	@classmethod
	def from_site(cls) -> "ShippingProviderRegistry":
		"""Build the registry of the installed site: built-in plus hooks."""
		providers: list["ShippingProvider"] = [ErpnextShippingRuleProvider()]
		for path in frappe.get_hooks(SHIPPING_PROVIDERS_HOOK, []) or []:
			provider = _resolve_hooked_provider(path)
			if provider is not None:
				providers.append(provider)
		return cls(providers)

	def providers(self) -> tuple["ShippingProvider", ...]:
		"""Every registered provider in deterministic order."""
		return tuple(self._providers_by_id.values())

	def get(self, provider_id: str) -> "ShippingProvider | None":
		"""Return the provider owning ``provider_id``, or ``None``."""
		return self._providers_by_id.get(provider_id)

	def list_options(self, context: ShippingQuoteContext) -> list[ShippingOptionQuote]:
		"""Concatenate every provider's quotes for ``context``, in order.

		Option ids stay unique: the first quote minting a public id wins,
		so a duplicate key can never make the id resolution ambiguous.
		"""
		quotes: dict[str, ShippingOptionQuote] = {}
		for provider in self._providers_by_id.values():
			for quote in self._provider_options(provider, context):
				quotes.setdefault(quote.option_id, quote)
		return list(quotes.values())

	def resolve_option(self, context: ShippingQuoteContext, option_id: str) -> ShippingOptionQuote | None:
		"""Return the quote ``option_id`` names for ``context``, or ``None``.

		Raises :class:`MalformedShippingOptionIdError` for an id the codec
		cannot decode; ``None`` means no registered provider serves it.
		"""
		provider_id, option_key = decode_option_id(option_id)
		provider = self.get(provider_id)
		if provider is None:
			return None
		quote = self._provider_quote(provider, context, option_key)
		if quote is None or not _conforming(provider, context, quote):
			return None
		return quote if quote.option_key == option_key else None

	def _provider_options(
		self, provider: "ShippingProvider", context: ShippingQuoteContext
	) -> list[ShippingOptionQuote]:
		try:
			contributed = list(provider.list_options(context) or [])
		except Exception:
			_log_failure(f"ceto shipping provider {provider.id}", frappe.get_traceback())
			return []
		return [quote for quote in contributed if _conforming(provider, context, quote)]

	def _provider_quote(
		self, provider: "ShippingProvider", context: ShippingQuoteContext, option_key: str
	) -> ShippingOptionQuote | None:
		try:
			if callable(getattr(provider, "get_option", None)):
				return provider.get_option(context, option_key)
			options = provider.list_options(context) or []
			return next((quote for quote in options if quote.option_key == option_key), None)
		except Exception:
			_log_failure(f"ceto shipping provider {provider.id}", frappe.get_traceback())
			return None


def _resolve_hooked_provider(path: str) -> "ShippingProvider | None":
	"""Resolve one ``ceto_shipping_providers`` hook entry, or ``None``.

	A path that does not resolve, a factory that fails and an object
	without the provider shape are logged and skipped.
	"""
	try:
		# Hook paths come exclusively from installed-app configuration. This is the
		# standard Frappe extension boundary, not request-controlled dynamic code.
		candidate = frappe.get_attr(path)
		provider = candidate() if callable(candidate) else candidate
	except Exception:
		_log_failure(f"ceto shipping provider hook {path}", frappe.get_traceback())
		return None
	provider_id = getattr(provider, "id", None)
	if not isinstance(provider_id, str) or not provider_id.strip():
		_log_failure(f"ceto shipping provider hook {path}", "does not expose a nonblank id")
		return None
	if not callable(getattr(provider, "list_options", None)):
		_log_failure(f"ceto shipping provider hook {path}", "does not expose list_options")
		return None
	return provider


def _conforming(provider: "ShippingProvider", context: ShippingQuoteContext, quote: object) -> bool:
	"""Whether one contributed quote honours the provider protocol."""
	if not isinstance(quote, ShippingOptionQuote):
		_log_failure(f"ceto shipping provider {provider.id}", f"returned a non-quote option: {quote!r}")
		return False
	if quote.provider_id != provider.id or quote.currency != context.currency:
		_log_failure(
			f"ceto shipping provider {provider.id}",
			f"returned a quote of another identity or currency: {quote.provider_id} / {quote.currency}",
		)
		return False
	return True


def _log_failure(title: str, message: str) -> None:
	frappe.log_error(title=title, message=message)
