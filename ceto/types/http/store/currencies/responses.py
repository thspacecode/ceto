"""Pinned response envelopes of the Medusa Store Currency routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
responds ``StoreCurrencyResponse`` and the list responds the pinned
``PaginatedResponse`` envelope — the exact ``{currencies, count, offset,
limit}`` body of the pinned 2.21.1 list handler.
"""

from pydantic import BaseModel

from ceto.types.http.store.currencies.entities import StoreCurrency


class StoreCurrencyResponse(BaseModel):
	"""Pinned ``StoreCurrencyResponse`` of ``@medusajs/types@2.21.1``."""

	currency: StoreCurrency


class StoreCurrencyListResponse(BaseModel):
	"""Pinned ``StoreCurrencyListResponse`` of ``@medusajs/types@2.21.1``."""

	currencies: list[StoreCurrency]
	count: int
	offset: int
	limit: int
