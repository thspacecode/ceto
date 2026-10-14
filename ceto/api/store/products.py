"""Thin Medusa Store Product endpoints (Phase 3 products slice)."""

from typing import Any

from ceto.api.store.publishable_key import StorePublishableKey
from ceto.routing import ceto_router
from ceto.services.catalog.products import ProductCatalog
from ceto.types.http.store.products import (
	StoreProductListParams,
	StoreProductListResponse,
	StoreProductOptionListParams,
	StoreProductOptionListResponse,
	StoreProductOptionParams,
	StoreProductOptionResponse,
	StoreProductParams,
	StoreProductResponse,
	StoreProductVariantListParams,
	StoreProductVariantListResponse,
)


@ceto_router.get("/store/products", allow_guest=True)
def list_products(**query: Any) -> StoreProductListResponse:
	"""Medusa ``list``: page the published assortment.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route through the shared boundary check. The pinned
	``StoreProductListParams`` validate the page before anything resolves:
	unknown keys — the upstream search, filter, operator-map, combinator,
	sort, ``fields`` and ``locale`` surfaces — and out-of-bounds pagination
	fail as ``400 invalid_data`` instead of being ignored or clamped. The
	one accepted extra key is the pinned pricing context (products slice
	decision 6): ``region_id`` prices the page's variants through the cart
	price-list authority, while an absent or blank value serves the
	projection unpriced. The order is the pinned deterministic one (item
	title then item code), and the envelope echoes the effective
	``offset`` / ``limit`` with the count taken over the whole published
	assortment.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductListParams.model_validate(query)
	return ProductCatalog().list(limit=filters.limit, offset=filters.offset, region_id=filters.region_id)


@ceto_router.get("/store/products/{id}", allow_guest=True)
def retrieve_product(id: str, **query: Any) -> StoreProductResponse:
	"""Medusa ``retrieve``: one published product by its derived public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id — and an ``Item`` outside the configured storefront
	roots, which does not exist on the Store surface — is the same masked
	``404 not_found``, never a ``500``. The pinned ``StoreProductParams``
	accept exactly the pricing context the detail route serves: a
	``region_id`` prices the detail's variants through the cart price-list
	authority, while every other key — a ``fields`` selector,
	``country_code``, ``province``, ``cart_id`` — is refused as ``400
	invalid_data`` before the product resolves, so detail always answers
	with the identical projection the list serves.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductParams.model_validate(query)
	return ProductCatalog().get(id, region_id=filters.region_id)


@ceto_router.get("/store/product-variants", allow_guest=True)
def list_product_variants(**query: Any) -> StoreProductVariantListResponse:
	"""Medusa ``list``: page the canonical variants surface.

	Guest-dispatchable with the publishable key as the only credential,
	exactly like the product list. The pinned
	``StoreProductVariantListParams`` validate the page before anything
	resolves — unknown keys and out-of-bounds pagination fail as ``400
	invalid_data`` — and accept the same one pricing-context key:
	``region_id`` prices every served variant through the cart price-list
	authority, an absent or blank value serves them unpriced. The surface
	serves every sellable unit of the published assortment in item-code
	order, and the envelope echoes the effective ``offset`` / ``limit``
	with the count taken over the whole surface.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductVariantListParams.model_validate(query)
	return ProductCatalog().variant_page(
		limit=filters.limit, offset=filters.offset, region_id=filters.region_id
	)


@ceto_router.get("/store/product-options", allow_guest=True)
def list_product_options(**query: Any) -> StoreProductOptionListResponse:
	"""Medusa ``list``: page the global option surface.

	Guest-dispatchable with the publishable key as the only credential,
	exactly like every product route. The pinned
	``StoreProductOptionListParams`` validate the page before anything
	resolves: unknown keys — including the upstream ``fields`` selector and
	any pricing context, which the option surface never serves — and
	out-of-bounds pagination fail as ``400 invalid_data``. The surface
	serves every family option of the published assortment title-then-id
	ordered, and the envelope echoes the effective ``offset`` / ``limit``
	with the count taken over the whole servable set.
	"""
	StorePublishableKey.from_request()
	filters = StoreProductOptionListParams.model_validate(query)
	return ProductCatalog().option_page(limit=filters.limit, offset=filters.offset)


@ceto_router.get("/store/product-options/{id}", allow_guest=True)
def retrieve_product_option(id: str, **query: Any) -> StoreProductOptionResponse:
	"""Medusa ``retrieve``: one published option by its derived public id.

	Guest-dispatchable with the publishable key required exactly like the
	list: an unknown id is the same masked ``404 not_found``, never a
	``500``. The pinned ``StoreProductOptionParams`` accepts no query at
	all — every key, including a ``fields`` selector the fixed projection
	never applies, is refused as ``400 invalid_data`` before the option
	resolves, so detail always answers with the identical projection the
	list serves.
	"""
	StorePublishableKey.from_request()
	StoreProductOptionParams.model_validate(query)
	return ProductCatalog().get_option(id)
