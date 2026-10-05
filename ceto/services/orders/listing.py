"""Store order listing (the Medusa ``GET /store/orders`` read model).

The authenticated list is strictly customer-scoped: upstream forces the
``customer_id`` filter to the authenticated actor, and Ceto resolves that
actor to its Customer with the same resolver the cart claim uses — the
service receives the customer, never a client-supplied id. The page is
further scoped at the query level, before anything is counted or loaded:

- **Effective owner** (Recorded Decision 2): the reference's
  ``owner_customer`` snapshot, with the completed cart's owner as the
  legacy fallback — the same ``OrderOwnership`` chain, resolved inside the
  query. Guest orders belong to no list (Recorded Decision 4).
- **Publishable-key scope** (Recorded Decision 5): orders inherit the
  completed cart's region / sales channel, and an unconstraining key
  constrains nothing — the same comparison the retrieve path masks as
  ``404``, applied as a filter here.
- **Live lineage**: the reference's Quotation is submitted and its Sales
  Order submitted — the pinned "actually completed" invariants, so state
  broken after the fact never appears in a list either.

Ordering is the Ceto decision ``creation DESC, order_id ASC`` (Recorded
Decision 7): newest first with the public id as the total tiebreak, so
pagination is deterministic. The exact count runs over the scoped query
before the page is sliced, and the pinned envelope echoes the effective
``offset`` / ``limit`` (non-negative; the read model bounds ``limit`` so
a page's bulk load stays bounded). The page itself is then served through
the existing ``OrderSerializer`` over :class:`OrderPageContext` — the
same representation the retrieve route returns, without per-order reads.

The ``id`` / ``status`` filters are the pinned domain (Recorded Decision
8): ids match public ``order_…`` ids, and ``status`` matches the single
value Ceto reports — every placed order is ``pending`` (Recorded Decision
6), so any other union member filters the page to empty, exactly as
upstream matches nothing. The HTTP validation of the union and the
rejection of combinators/sort/soft-delete params belong to the pinned
``StoreOrderFilters`` contract at the route layer, not to this service.
"""

from typing import TYPE_CHECKING, Any

import frappe
from frappe.query_builder import Criterion, Order
from frappe.query_builder.functions import Count
from frappe.utils import cint

from ceto.routing.exceptions import UnauthorizedError
from ceto.services.orders.access import PublishableKeyScope
from ceto.services.orders.context import OrderPageContext
from ceto.services.orders.serialization import OrderSerializer
from ceto.services.serialization import select_fields
from ceto.types.http.store.orders import StoreOrder
from ceto.types.http.store.orders.manifest import (
	ORDER_LIST_DEFAULT_LIMIT,
	ORDER_LIST_DEFAULT_OFFSET,
	ORDER_LIST_MAX_LIMIT,
)

if TYPE_CHECKING:
	from frappe.model.document import Document


class OrderListing:
	"""List a customer's placed orders, page by page."""

	def __init__(self, orders: OrderSerializer | None = None) -> None:
		self.orders = orders or OrderSerializer()

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
		"""Return the pinned ``{orders, count, offset, limit}`` envelope.

		``owner_customer`` is the authenticated caller's Customer (the
		handler resolves the session; the service never accepts a
		client-supplied id), ``key`` the publishable key scope every Store
		route resolves. ``ids`` / ``statuses`` are the pinned filters —
		single values or lists — and ``fields`` is the shared selector
		applied to every served order, exactly as on retrieve.
		"""
		if not owner_customer:
			raise UnauthorizedError("Order list requires an authenticated customer")
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), ORDER_LIST_MAX_LIMIT)
		if statuses and not self._reported_statuses(statuses):
			return {"orders": [], "count": 0, "offset": offset, "limit": limit}

		conditions = self._scope_conditions(owner_customer, key, ids)
		count = self._count(conditions)
		rows = self._page(conditions, limit, offset) if count else []
		context = OrderPageContext(rows) if rows else None
		orders = []
		for row in rows:
			order = self.orders.serialize(
				context.order(row.name),
				context.sales_order(row.sales_order),
				context.cart(row.cart_id),
				context=context,
			)
			orders.append(select_fields(order, fields, entity="order"))
		return {"orders": orders, "count": count, "offset": offset, "limit": limit}

	@staticmethod
	def _reported_statuses(statuses: "str | list[str]") -> "set[str]":
		"""Return the requested statuses Ceto can report (Decision 6).

		Every placed order reports the pinned model default; requested
		statuses outside it simply match nothing, like upstream.
		"""
		requested = {statuses} if isinstance(statuses, str) else set(statuses)
		return requested & {StoreOrder.model_fields["status"].default}

	@staticmethod
	def _scope_conditions(
		owner_customer: str, key: PublishableKeyScope, ids: "str | list[str] | None"
	) -> list:
		"""Build the scoped ``WHERE`` conditions shared by count and page."""
		references = frappe.qb.DocType("Ceto Order Reference")
		carts = frappe.qb.DocType("Ceto Cart Reference")

		# The effective owner (Recorded Decision 2): the reference's
		# snapshot, the completed cart's owner as the legacy fallback.
		conditions = [
			(references.owner_customer == owner_customer)
			| (
				(references.owner_customer.isnull() | (references.owner_customer == ""))
				& (carts.owner_customer == owner_customer)
			)
		]
		# A key's constraining scope never excludes an unconstrained
		# reference — the comparison OrderAccess masks as 404.
		if key.region_id:
			conditions.append(
				carts.region_id.isnull() | (carts.region_id == "") | (carts.region_id == key.region_id)
			)
		if key.sales_channel_id:
			conditions.append(
				carts.sales_channel_id.isnull()
				| (carts.sales_channel_id == "")
				| (carts.sales_channel_id == key.sales_channel_id)
			)
		if ids:
			order_ids = [ids] if isinstance(ids, str) else list(ids)
			conditions.append(references.order_id.isin(order_ids))
		# The pinned "actually completed" lineage: a placed order's
		# Quotation and Sales Order are both submitted.
		conditions.append(frappe.qb.DocType("Quotation").docstatus == 1)
		conditions.append(frappe.qb.DocType("Sales Order").docstatus == 1)
		return conditions

	@classmethod
	def _count(cls, conditions: list) -> int:
		"""Count the scoped orders exactly, before any pagination."""
		references, carts, quotations, sales_orders = cls._tables()
		result = (
			frappe.qb.from_(references)
			.inner_join(carts)
			.on(references.cart_id == carts.name)
			.inner_join(quotations)
			.on(carts.quotation == quotations.name)
			.inner_join(sales_orders)
			.on(references.sales_order == sales_orders.name)
			.select(Count(references.name))
			.where(Criterion.all(conditions))
			.run()
		)
		return cint(result[0][0]) if result else 0

	@classmethod
	def _page(cls, conditions: list, limit: int, offset: int) -> "list[Document]":
		"""Slice one page off the scoped query, deterministically ordered.

		``creation DESC, order_id ASC`` (Recorded Decision 7); the rows
		become ordinary order reference documents for the page context.
		"""
		references, carts, quotations, sales_orders = cls._tables()
		rows = (
			frappe.qb.from_(references)
			.inner_join(carts)
			.on(references.cart_id == carts.name)
			.inner_join(quotations)
			.on(carts.quotation == quotations.name)
			.inner_join(sales_orders)
			.on(references.sales_order == sales_orders.name)
			.select(references.star)
			.where(Criterion.all(conditions))
			.orderby(references.creation, order=Order.desc)
			.orderby(references.order_id, order=Order.asc)
			.limit(limit)
			.offset(offset)
			.run(as_dict=True)
		)
		return [frappe.get_doc({"doctype": "Ceto Order Reference", **row}) for row in rows]

	@staticmethod
	def _tables() -> tuple:
		"""The joined read-model tables: order, cart, Quotation, Sales Order."""
		return (
			frappe.qb.DocType("Ceto Order Reference"),
			frappe.qb.DocType("Ceto Cart Reference"),
			frappe.qb.DocType("Quotation"),
			frappe.qb.DocType("Sales Order"),
		)
