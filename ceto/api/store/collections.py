"""Thin Medusa Store Collection endpoints (Phase 2 slice 2B)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.catalog.collections import CollectionDirectory
from ceto.types.http.store.collections import (
	StoreCollectionListParams,
	StoreCollectionListResponse,
	StoreCollectionParams,
	StoreCollectionResponse,
)


@ceto_router.get("/store/collections", allow_guest=True)
def list_collections(**query: Any) -> StoreCollectionListResponse:
	"""Medusa ``list``: page the Ceto-stored collections.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreCollectionListParams`` validate the page before anything resolves:
	unknown keys and out-of-bounds pagination fail as ``400 invalid_data``
	instead of being ignored or clamped. The order is the upstream pinned
	default sort (creation descending, record id breaking ties), and the
	envelope echoes the effective ``offset`` / ``limit`` with the count taken
	over the whole stored set.
	"""
	StorePublishableKey.from_request()
	filters = StoreCollectionListParams.model_validate(query)
	return CollectionDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/collections/{id}", allow_guest=True)
def retrieve_collection(id: str, **query: Any) -> StoreCollectionResponse:
	"""Medusa ``retrieve``: one stored collection by its minted public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id is the same masked ``404 not_found``, never a
	``500``. The pinned ``StoreCollectionParams`` accepts no query at all —
	every key, including a ``fields`` selector, is refused as ``400
	invalid_data`` before the collection resolves, so detail always answers
	with the identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	StoreCollectionParams.model_validate(query)
	return CollectionDirectory().get(id)
