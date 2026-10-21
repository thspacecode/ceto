"""Pinned response envelopes of the Medusa Store Product Type routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreProductTypeResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{product_types, count, offset,
limit}`` body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.product_types.entities import StoreProductType


class StoreProductTypeResponse(BaseModel):
	"""Pinned ``StoreProductTypeResponse`` of ``@medusajs/types@2.21.1``."""

	product_type: StoreProductType


class StoreProductTypeListResponse(BaseModel):
	"""Pinned ``StoreProductTypeListResponse`` of ``@medusajs/types@2.21.1``."""

	product_types: list[StoreProductType]
	count: int
	offset: int
	limit: int
