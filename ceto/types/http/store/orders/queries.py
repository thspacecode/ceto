"""Pinned query contracts of the Medusa Store Order retrieve/list routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``: retrieve takes
a bare ``SelectParams`` (``StoreGetOrderParams`` — ``fields`` only) and the
list takes ``StoreOrderFilters`` (``id`` / ``status``, each a single value or
a list, ``status`` over the pinned ``OrderStatus`` union) with the
pagination of ``FindParams``. The list defaults mirror the upstream server
validator (``createFindParams({offset: 0, limit: 50})``), pinned in the
manifest beside the Ceto read-model page bound (``ORDER_LIST_MAX_LIMIT``):
one page is at most a hundred orders and the page numbers are non-negative,
so the bulk page load stays bounded — a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped.

The upstream validator additionally merges the ``$and``/``$or`` combinators
and accepts the ``FindParams`` ``order`` sort expression and ``with_deleted``
flag; Ceto pins none of them (Recorded Decision 8 of
``docs/orders/field-mapping.md``): the strict models reject them instead of
silently ignoring them, so a client never receives a page it cannot
reproduce. ``fields`` behaves as on the cart routes — the same selector
implementation the handlers apply to the serialized order(s).
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.orders.entities import OrderStatus
from ceto.types.http.store.orders.manifest import (
	ORDER_LIST_DEFAULT_LIMIT,
	ORDER_LIST_DEFAULT_OFFSET,
	ORDER_LIST_MAX_LIMIT,
)


class _StoreOrderSelectParams(BaseModel):
	"""Shared ``SelectParams`` column of the order query contracts.

	The pinned ``fields`` selector is a single comma-separated string, exactly
	as on the cart routes; unknown keys are rejected like on every core
	payload.
	"""

	model_config = ConfigDict(extra="forbid")

	fields: str | None = None


class StoreGetOrderParams(_StoreOrderSelectParams):
	"""Query params of ``GET /store/orders/{id}``.

	Mirrors the pinned ``StoreGetOrderParams`` of ``@medusajs/types@2.21.1``:
	a bare ``SelectParams``, so ``fields`` is the only accepted key.
	"""


class StoreOrderFilters(_StoreOrderSelectParams):
	"""Query params of ``GET /store/orders``.

	Mirrors the pinned ``StoreOrderFilters`` of ``@medusajs/types@2.21.1``
	with the ``FindParams`` pagination. ``order``, ``with_deleted``, ``$and``
	and ``$or`` are deliberately absent and rejected as unknown fields
	(Recorded Decision 8), as is every filter outside the pinned ``id`` /
	``status`` — the list handler forces the caller's own customer id, so it
	is never client-supplied. The pagination carries the Ceto read-model
	bounds: ``limit`` is the pinned default capped at one page's bulk load,
	``offset`` non-negative.
	"""

	limit: int = Field(default=ORDER_LIST_DEFAULT_LIMIT, ge=0, le=ORDER_LIST_MAX_LIMIT)
	offset: int = Field(default=ORDER_LIST_DEFAULT_OFFSET, ge=0)
	id: str | list[str] | None = None
	status: OrderStatus | list[OrderStatus] | None = None
