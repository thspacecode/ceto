"""Pinned response envelopes of the Medusa Store Order routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: retrieve
and every transfer route respond ``StoreOrderResponse`` (the SDK inlines the
``{order: StoreOrder}`` body) and the list responds the pinned
``PaginatedResponse`` envelope. The shared ``PaginatedResponse`` type also
declares an optional ``estimate_count`` (the index-engine feature flag), but
the pinned orders list handler never emits it — no ``estimate_count`` appears
anywhere in the 2.21.1 orders API — so Ceto pins the envelope without it
(``docs/orders/field-mapping.md``).
"""

from pydantic import BaseModel

from ceto.types.http.store.orders.entities import StoreOrder


class StoreOrderResponse(BaseModel):
	"""Pinned ``StoreOrderResponse`` of ``@medusajs/types@2.21.1``."""

	order: StoreOrder


class StoreOrderListResponse(BaseModel):
	"""Pinned ``StoreOrderListResponse`` of ``@medusajs/types@2.21.1``.

	The exact ``{orders, count, offset, limit}`` envelope of the pinned
	``PaginatedResponse`` for the orders list — deliberately without the
	optional ``estimate_count`` (Ceto has no index engine).
	"""

	orders: list[StoreOrder]
	count: int
	offset: int
	limit: int
