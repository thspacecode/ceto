"""Pinned response envelopes of the Medusa Store Region routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreRegionResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{regions, count, offset, limit}``
body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.regions.entities import StoreRegion


class StoreRegionResponse(BaseModel):
	"""Pinned ``StoreRegionResponse`` of ``@medusajs/types@2.21.1``."""

	region: StoreRegion


class StoreRegionListResponse(BaseModel):
	"""Pinned ``StoreRegionListResponse`` of ``@medusajs/types@2.21.1``."""

	regions: list[StoreRegion]
	count: int
	offset: int
	limit: int
