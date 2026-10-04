"""Store order retrieval (the Medusa ``GET /store/orders/{id}`` service).

Composed from pieces that already exist: ``OrderAccess`` resolves the id
under lineage and publishable-key scope (every failure the same ``404
not_found``), ``OrderSerializer`` derives the canonical ``StoreOrder`` JSON
from those records, and the shared entity-neutral selector applies the
route's ``fields`` — retrieval supports the pinned ``StoreGetOrderParams``
without owning any representation. The response envelope stays the API
layer's job, as on carts.
"""

from typing import Any

from ceto.services.orders.access import OrderAccess, PublishableKeyScope
from ceto.services.orders.serialization import OrderSerializer
from ceto.services.serialization import select_fields


class OrderService:
	"""Retrieve placed orders through their public ids."""

	def __init__(self, access: OrderAccess | None = None, orders: OrderSerializer | None = None) -> None:
		self.access = access or OrderAccess()
		self.orders = orders or OrderSerializer()

	def retrieve(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		fields: str | None = None,
	) -> dict[str, Any]:
		"""Return the pinned ``StoreOrder`` JSON of ``order_id``.

		``key`` is resolved as every Store route resolves it
		(``CartPublishableKey.from_request``); an order outside the key's
		region or sales channel is the same ``404 not_found`` as an
		unknown one. ``fields`` is the shared selector: plain tokens
		narrow, ``+``/``-`` extend or remove, unknown fields fail closed
		as ``400 invalid_data``.
		"""
		order_reference, sales_order, reference = self.access.resolve(order_id, key)
		order = self.orders.serialize(order_reference, sales_order, reference)
		return select_fields(order, fields, entity="order")
