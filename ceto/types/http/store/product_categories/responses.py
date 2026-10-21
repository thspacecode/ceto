"""Pinned response envelopes of the Medusa Store Product Category routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreProductCategoryResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{product_categories, count,
offset, limit}`` body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.product_categories.entities import StoreProductCategory


class StoreProductCategoryResponse(BaseModel):
	"""Pinned ``StoreProductCategoryResponse`` of ``@medusajs/types@2.21.1``."""

	product_category: StoreProductCategory


class StoreProductCategoryListResponse(BaseModel):
	"""Pinned ``StoreProductCategoryListResponse`` of ``@medusajs/types@2.21.1``."""

	product_categories: list[StoreProductCategory]
	count: int
	offset: int
	limit: int
