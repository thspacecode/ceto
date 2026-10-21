"""Thin Medusa Store Currency endpoints (Phase 1 slice B)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.reference.currencies import CurrencyDirectory
from ceto.types.http.store.currencies import (
	StoreCurrencyListResponse,
	StoreCurrencyResponse,
	StoreGetCurrencyListParams,
	StoreGetCurrencyParams,
)


@ceto_router.get("/store/currencies", allow_guest=True)
def list_currencies(**query: Any) -> StoreCurrencyListResponse:
	"""Medusa ``list``: page the currencies the configured regions reference.

	Guest-dispatchable with the publishable key required exactly as on every
	Store route through the shared boundary check. The pinned
	``StoreGetCurrencyListParams`` validate the page before anything
	resolves: unknown keys and out-of-bounds pagination fail as ``400
	invalid_data`` instead of being ignored or clamped. The list is scoped,
	never the whole ERPNext currency table, and the envelope echoes the
	effective ``offset`` / ``limit`` with the count taken over the whole
	referenced set.
	"""
	StorePublishableKey.from_request()
	filters = StoreGetCurrencyListParams.model_validate(query)
	return CurrencyDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/currencies/{code}", allow_guest=True)
def retrieve_currency(code: str, **query: Any) -> StoreCurrencyResponse:
	"""Medusa ``retrieve``: one referenced currency by its Medusa code.

	Guest-dispatchable with the publishable key required exactly like the
	list: the code resolves case-insensitively, and a currency no valid
	region references — like an unknown one — is the same masked ``404
	not_found``, never a ``500``. The pinned ``StoreGetCurrencyParams``
	accepts no query yet — every key, including a ``fields`` selector, is
	refused as ``400 invalid_data`` before the currency resolves, so detail
	always answers with the identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	StoreGetCurrencyParams.model_validate(query)
	return CurrencyDirectory().get(code)
