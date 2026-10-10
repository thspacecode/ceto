"""Thin Medusa Store Product Tag endpoints (Phase 2 tags behavior slice)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.catalog.product_tags import ProductTagDirectory
from ceto.types.http.store.product_tags import (
	StoreProductTagListParams,
	StoreProductTagListResponse,
	StoreProductTagParams,
	StoreProductTagResponse,
)


@ceto_router.get("/store/product-tags", allow_guest=True)
def list_product_tags(**query: Any) -> StoreProductTagListResponse:
	"""Medusa ``list``: page the served catalog tags.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreProductTagListParams`` validate the page before anything
	resolves: unknown keys and out-of-bounds pagination fail as ``400
	invalid_data`` instead of being ignored or clamped. The order is the
	pinned deterministic one (value ascending), and the envelope echoes the
	effective ``offset`` / ``limit`` with the count taken over the whole
	served set.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductTagListParams.model_validate(query)
	return ProductTagDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/product-tags/{id}", allow_guest=True)
def retrieve_product_tag(id: str, **query: Any) -> StoreProductTagResponse:
	"""Medusa ``retrieve``: one served tag by its derived public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id is the same masked ``404 not_found``, never a
	``500``. The pinned ``StoreProductTagParams`` accepts no query at all —
	every key, including a ``fields`` selector, is refused as ``400
	invalid_data`` before the tag resolves, so detail always answers with
	the identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	StoreProductTagParams.model_validate(query)
	return ProductTagDirectory().get(id)
