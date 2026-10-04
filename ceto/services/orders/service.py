"""Store order services (the Medusa ``GET /store/orders`` surface).

Composed from pieces that already exist: ``OrderAccess`` resolves one id
under lineage and publishable-key scope (every failure the same ``404
not_found``), ``OrderListing`` pages a customer's orders out of the same
read model, and ``OrderSerializer`` derives the canonical ``StoreOrder``
JSON from those records. The shared entity-neutral selector applies the
routes' ``fields`` — the services support the pinned contracts without
owning any representation. The response envelope stays the API layer's
job, as on carts.
"""

from typing import Any

from ceto.services.orders.access import OrderAccess, PublishableKeyScope
from ceto.services.orders.listing import OrderListing
from ceto.services.orders.serialization import OrderSerializer
from ceto.services.serialization import select_fields
from ceto.types.http.store.orders.manifest import ORDER_LIST_DEFAULT_LIMIT, ORDER_LIST_DEFAULT_OFFSET


class OrderService:
	"""Retrieve and list placed orders."""

	def __init__(
		self,
		access: OrderAccess | None = None,
		orders: OrderSerializer | None = None,
		listing: OrderListing | None = None,
	) -> None:
		self.access = access or OrderAccess()
		self.orders = orders or OrderSerializer()
		self.listing = listing or OrderListing(self.orders)

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

	def list(
		self,
		owner_customer: str,
		key: PublishableKeyScope,
		*,
		ids: "str | list[str] | None" = None,
		statuses: "str | list[str] | None" = None,
		limit: int = ORDER_LIST_DEFAULT_LIMIT,
		offset: int = ORDER_LIST_DEFAULT_OFFSET,
		fields: "str | None" = None,
	) -> "dict[str, Any]":
		"""Return the authenticated customer's placed orders, page by page.

		Delegates to the listing read model (:class:`OrderListing`): the
		page is scoped to the effective owner and the publishable key,
		ordered ``creation DESC, order_id ASC``, counted exactly before
		pagination and serialized through the same ``OrderSerializer`` as
		retrieve — the pinned ``{orders, count, offset, limit}`` envelope
		with the shared ``fields`` selector applied per order.
		"""
		return self.listing.list(
			owner_customer,
			key,
			ids=ids,
			statuses=statuses,
			limit=limit,
			offset=offset,
			fields=fields,
		)
