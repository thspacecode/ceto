"""Pinned response envelopes of the Medusa Store Product Tag routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreProductTagResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{product_tags, count, offset,
limit}`` body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.product_tags.entities import StoreProductTag


class StoreProductTagResponse(BaseModel):
	"""Pinned ``StoreProductTagResponse`` of ``@medusajs/types@2.21.1``."""

	product_tag: StoreProductTag


class StoreProductTagListResponse(BaseModel):
	"""Pinned ``StoreProductTagListResponse`` of ``@medusajs/types@2.21.1``."""

	product_tags: list[StoreProductTag]
	count: int
	offset: int
	limit: int
