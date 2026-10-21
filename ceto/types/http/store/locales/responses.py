"""Response envelope of the Store Locale route.

The pinned ``StoreLocaleListResponse`` of ``@medusajs/types@2.21.1`` is
``{locales: StoreLocale[]}`` — unpaged, no count/offset/limit. Ceto serves
exactly that envelope plus one **labeled Ceto extension**: ``default_locale``.
The extension exists because Ceto's locale list is provisioned from the
enabled Frappe ``Language`` records (not an i18n module), so the locale a
storefront should fall back to is a Ceto decision, documented and served
instead of left for every client to re-derive (see
``docs/reference-data/field-mapping.md``).
"""

from pydantic import BaseModel

from ceto.types.http.store.locales.entities import StoreLocale


class StoreLocaleListResponse(BaseModel):
	"""Pinned ``StoreLocaleListResponse`` plus the labeled Ceto extension.

	``default_locale`` is **not** part of ``@medusajs/types@2.21.1``. It
	resolves deterministically: the ``ceto_cart.default_locale`` site
	configuration when it names an enabled ``Language``, else the site
	default language when enabled, else ``en`` when enabled, else the first
	enabled language by code, else ``None`` when no language is enabled.
	"""

	locales: list[StoreLocale]
	default_locale: str | None = None
