"""Pinned contract manifest for the Store Locale route.

Source of truth: <https://docs.medusajs.com/api/store/locales>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 1 slice A pins the contract only — no locale handler is implemented
here and no route is registered on the router. The manifest is pure Python
(no Frappe imports) so it can drive request validation codegen and be tested
standalone.

The route shape is pinned to the core ``HttpTypes`` of
``@medusajs/types@2.21.1`` (``http/locale/store``): ``GET /store/locales``
answering ``StoreLocaleListResponse``, covered by the ``sdk.store.locale.list``
SDK method. Upstream gates that route behind its ``translation`` feature flag
and backs it with the i18n locale module — **Ceto always serves it**, backed
by its own provisioning: the enabled Frappe ``Language`` records plus the
deterministic default documented on the response model. That provisioning is
Ceto-owned, and every response column the pinned type does not declare —
exactly one, ``default_locale`` — is a **labeled Ceto extension**
(``docs/reference-data/field-mapping.md``), not an ``HttpTypes`` member.
"""

from dataclasses import dataclass

LOCALE_API_SOURCE_URL = "https://docs.medusajs.com/api/store/locales"

LOCALE_SDK_PACKAGE = "@medusajs/js-sdk"

LOCALE_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
LOCALE_TYPES_PACKAGE = "@medusajs/types"

LOCALE_TYPES_VERSION = "2.21.1"

#: Locale methods directly exposed by the pinned SDK version — the pinned
#: route is covered by ``sdk.store.locale.list``.
LOCALE_SDK_METHODS = ("list",)


@dataclass(frozen=True, slots=True)
class LocaleRoute:
	"""One pinned Store Locale route contract."""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None


LOCALE_ROUTES: tuple[LocaleRoute, ...] = (
	LocaleRoute(
		method="GET",
		path="/store/locales",
		request_type=None,
		response_type="StoreLocaleListResponse",
		auth="publishable-key",
		sdk_method="list",
	),
)
