"""Thin Medusa Store Product Type endpoints (Phase 2 slice 2B)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.catalog.product_types import ProductTypeDirectory
from ceto.types.http.store.product_types import (
	StoreProductTypeListParams,
	StoreProductTypeListResponse,
	StoreProductTypeParams,
	StoreProductTypeResponse,
)


@ceto_router.get("/store/product-types", allow_guest=True)
def list_product_types(**query: Any) -> StoreProductTypeListResponse:
	"""Medusa ``list``: page the Ceto-stored curated product types.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreProductTypeListParams`` validate the page before anything
	resolves: unknown keys and out-of-bounds pagination fail as ``400
	invalid_data`` instead of being ignored or clamped. The order is the
	pinned deterministic one (value ascending, record id breaking ties), and
	the envelope echoes the effective ``offset`` / ``limit`` with the count
	taken over the whole stored set.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductTypeListParams.model_validate(query)
	return ProductTypeDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/product-types/{id}", allow_guest=True)
def retrieve_product_type(id: str, **query: Any) -> StoreProductTypeResponse:
	"""Medusa ``retrieve``: one stored type by its minted public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id is the same masked ``404 not_found``, never a
	``500``. The pinned ``StoreProductTypeParams`` accepts no query at all —
	every key, including a ``fields`` selector, is refused as ``400
	invalid_data`` before the type resolves, so detail always answers with
	the identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	StoreProductTypeParams.model_validate(query)
	return ProductTypeDirectory().get(id)
