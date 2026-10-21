"""Read-only Store locale projections from the enabled Frappe Languages.

Ceto's locales are the enabled ``Language`` records — the same records the
desk itself offers, projected onto the pinned ``StoreLocale`` shape and
ordered deterministically by code. The list is cheap and stable: one indexed
read, no per-locale resolution.

The deterministic default (the labeled Ceto extension on the response)
resolves in a fixed order: the ``ceto_cart.default_locale`` site
configuration when it names an enabled language, else the site default
language (``System Settings.language``) when enabled, else ``en`` when
enabled, else the first enabled language by code — ``None`` only when no
language is enabled at all, so the response never invents a locale.
"""

import frappe

from ceto.config.cart import cart_settings
from ceto.types.http.store.locales import StoreLocale, StoreLocaleListResponse

FALLBACK_LOCALE = "en"


class LocaleDirectory:
	"""Project the enabled Frappe Languages as pinned Store locales."""

	def list(self) -> StoreLocaleListResponse:
		"""Return the pinned ``{locales}`` envelope plus the labeled default."""
		locales = frappe.get_all(
			"Language",
			filters={"enabled": 1},
			fields=("name", "language_name"),
			order_by="name",
		)
		codes = [row.name for row in locales]
		return StoreLocaleListResponse(
			locales=[StoreLocale(code=row.name, name=row.language_name or row.name) for row in locales],
			default_locale=self._default_locale(codes),
		)

	def _default_locale(self, codes: list[str]) -> str | None:
		"""Resolve the deterministic default from the enabled codes."""
		enabled = set(codes)
		configured = cart_settings().get("default_locale")
		if configured and str(configured) in enabled:
			return str(configured)
		site_language = frappe.db.get_single_value("System Settings", "language")
		if site_language and site_language in enabled:
			return site_language
		if FALLBACK_LOCALE in enabled:
			return FALLBACK_LOCALE
		return codes[0] if codes else None
