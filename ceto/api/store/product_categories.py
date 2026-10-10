"""Thin Medusa Store Product Category endpoints (Phase 2 slice 2C)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.catalog.product_categories import ProductCategoryDirectory
from ceto.types.http.store.product_categories import (
	StoreProductCategoryListParams,
	StoreProductCategoryListResponse,
	StoreProductCategoryParams,
	StoreProductCategoryResponse,
)


@ceto_router.get("/store/product-categories", allow_guest=True)
def list_product_categories(**query: Any) -> StoreProductCategoryListResponse:
	"""Medusa ``list``: page the published Item Group tree.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreProductCategoryListParams`` validate the page before anything
	resolves: unknown keys — including the upstream search, filters, the
	tree expansion flags and any ``fields`` selector — and out-of-bounds
	pagination fail as ``400 invalid_data`` instead of being ignored or
	clamped. The order is the pinned deterministic one (``lft`` ascending,
	the NestedSet pre-order walk, node name breaking ties), and the envelope
	echoes the effective ``offset`` / ``limit`` with the count taken over the
	whole published set.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductCategoryListParams.model_validate(query)
	return ProductCategoryDirectory().list(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/product-categories/{id}", allow_guest=True)
def retrieve_product_category(id: str, **query: Any) -> StoreProductCategoryResponse:
	"""Medusa ``retrieve``: one published category by its derived public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id — and an ``Item Group`` outside the configured
	storefront roots, which does not exist on the Store surface — is the
	same masked ``404 not_found``, never a ``500``. The pinned
	``StoreProductCategoryParams`` accepts no query at all — every key,
	including a ``fields`` selector or the ``include_ancestors_tree`` /
	``include_descendants_tree`` flags, is refused as ``400 invalid_data``
	before the category resolves, so detail always answers with the
	identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	StoreProductCategoryParams.model_validate(query)
	return ProductCategoryDirectory().get(id)
