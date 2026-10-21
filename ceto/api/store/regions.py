"""Thin Medusa Store Region endpoints (Phase 1 slice B)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.reference.regions import RegionDirectory
from ceto.types.http.store.regions import (
	StoreGetRegionParams,
	StoreRegionFilters,
	StoreRegionListResponse,
	StoreRegionResponse,
)


@ceto_router.get("/store/regions", allow_guest=True)
def list_regions(**query: Any) -> StoreRegionListResponse:
	"""Medusa ``list``: page the configured commerce regions.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreRegionFilters`` validate the page before anything resolves:
	unknown keys and out-of-bounds pagination fail as ``400 invalid_data``
	instead of being ignored or clamped. Unservable regions are invisible to
	the page — never errors — and the envelope echoes the effective
	``offset`` / ``limit`` with the count taken over the whole servable set.
	"""
	StorePublishableKey.from_request()
	filters = StoreRegionFilters.model_validate(query)
	return RegionDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/regions/{id}", allow_guest=True)
def retrieve_region(id: str, **query: Any) -> StoreRegionResponse:
	"""Medusa ``retrieve``: one servable region by its configured id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown or unservable id is the same masked ``404 not_found``,
	never a ``500``, so a broken region overlay cannot surface. The pinned
	``StoreGetRegionParams`` accepts no query yet — every key, including a
	``fields`` selector, is refused as ``400 invalid_data`` before the
	region resolves, so detail always answers with the identical projection
	the list serves.
	"""
	StorePublishableKey.from_request()
	StoreGetRegionParams.model_validate(query)
	return RegionDirectory().get(id)
