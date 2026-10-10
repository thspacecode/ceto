"""Pinned response envelopes of the Medusa Store Collection routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreCollectionResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{collections, count, offset,
limit}`` body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.collections.entities import StoreCollection


class StoreCollectionResponse(BaseModel):
	"""Pinned ``StoreCollectionResponse`` of ``@medusajs/types@2.21.1``."""

	collection: StoreCollection


class StoreCollectionListResponse(BaseModel):
	"""Pinned ``StoreCollectionListResponse`` of ``@medusajs/types@2.21.1``."""

	collections: list[StoreCollection]
	count: int
	offset: int
	limit: int
