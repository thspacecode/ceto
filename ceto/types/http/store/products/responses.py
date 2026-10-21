"""Pinned response envelopes of the Medusa Store product routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: the
product and option detail routes respond ``StoreProductResponse`` /
``StoreProductOptionResponse`` and the three lists respond the pinned
``PaginatedResponse`` envelopes — the exact ``{products, count, offset,
limit}``, ``{variants, count, offset, limit}`` and ``{product_options,
count, offset, limit}`` bodies of the pinned 2.21.1 list handlers. There is
no variants detail envelope: the canonical variants surface is the list
route alone (products slice decision 5).
"""

from pydantic import BaseModel

from ceto.types.http.store.products.entities import (
	StoreProduct,
	StoreProductOption,
	StoreProductVariant,
)


class StoreProductResponse(BaseModel):
	"""Pinned ``StoreProductResponse`` of ``@medusajs/types@2.21.1``."""

	product: StoreProduct


class StoreProductListResponse(BaseModel):
	"""Pinned ``StoreProductListResponse`` of ``@medusajs/types@2.21.1``."""

	products: list[StoreProduct]
	count: int
	offset: int
	limit: int


class StoreProductVariantListResponse(BaseModel):
	"""Pinned ``StoreProductVariantListResponse`` of ``@medusajs/types@2.21.1``."""

	variants: list[StoreProductVariant]
	count: int
	offset: int
	limit: int


class StoreProductOptionResponse(BaseModel):
	"""Pinned ``StoreProductOptionResponse`` of ``@medusajs/types@2.21.1``."""

	product_option: StoreProductOption


class StoreProductOptionListResponse(BaseModel):
	"""Pinned ``StoreProductOptionListResponse`` of ``@medusajs/types@2.21.1``."""

	product_options: list[StoreProductOption]
	count: int
	offset: int
	limit: int
