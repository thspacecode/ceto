"""Thin Medusa Store Locale endpoint (Phase 1 slice B)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.reference.locales import LocaleDirectory
from ceto.types.http.store.locales import StoreLocaleListParams, StoreLocaleListResponse


@ceto_router.get("/store/locales", allow_guest=True)
def list_locales(**query: Any) -> StoreLocaleListResponse:
	"""Medusa ``list``: the enabled Frappe Languages plus the labeled default.

	Guest-dispatchable with the publishable key required exactly as on every
	Store route through the shared boundary check — upstream serves the
	route behind its ``translation`` feature flag, Ceto always serves it on
	its own provisioning. Upstream pins no query for the unpaged route, so
	the strict-empty ``StoreLocaleListParams`` refuses every key as ``400
	invalid_data`` before the languages resolve; the response is the pinned
	``{locales}`` envelope plus the deterministic ``default_locale`` Ceto
	extension.
	"""
	StorePublishableKey.from_request()
	StoreLocaleListParams.model_validate(query)
	return LocaleDirectory().list()
