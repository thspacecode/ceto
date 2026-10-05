"""Store order services (the Medusa ``GET /store/orders`` surface).

Composed from pieces that already exist: ``OrderAccess`` resolves one id
under lineage and publishable-key scope (every failure the same ``404
not_found``), ``OrderListing`` pages a customer's orders out of the same
read model, ``OrderTransfer`` mints and cancels pending ownership-transfer
requests under the order's row lock, and ``OrderSerializer`` derives the
canonical ``StoreOrder`` JSON from those records. The shared entity-neutral selector applies the
routes' ``fields`` — the services support the pinned contracts without
owning any representation. The response envelope stays the API layer's
job, as on carts.
"""

from typing import Any

from ceto.services.orders.access import OrderAccess, PublishableKeyScope
from ceto.services.orders.listing import OrderListing
from ceto.services.orders.serialization import OrderSerializer
from ceto.services.orders.transfer import OrderTransfer
from ceto.services.serialization import select_fields
from ceto.types.http.store.orders.manifest import ORDER_LIST_DEFAULT_LIMIT, ORDER_LIST_DEFAULT_OFFSET


class OrderService:
	"""Retrieve and list placed orders, and request or cancel their ownership transfer."""

	def __init__(
		self,
		access: OrderAccess | None = None,
		orders: OrderSerializer | None = None,
		listing: OrderListing | None = None,
		transfers: OrderTransfer | None = None,
	) -> None:
		self.access = access or OrderAccess()
		self.orders = orders or OrderSerializer()
		self.listing = listing or OrderListing(self.orders)
		self.transfers = transfers or OrderTransfer(self.access, self.orders)

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

	def request_transfer(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		requested_by: str,
		requester_email: str | None = None,
		description: str | None = None,
		update_order_email: bool | None = None,
	) -> dict[str, Any]:
		"""Request ownership of ``order_id`` for the authenticated customer.

		Delegates to the transfer component (:class:`OrderTransfer`): the
		order reference is row-locked before any check, resolution is the
		retrieve path's masked ``404 not_found``, eligibility is guest-only
		(Recorded Decision 9) and one live pending request is enforced under
		the lock (Recorded Decision 11). ``requested_by`` / ``requester_email``
		are the authenticated caller's Customer and email, resolved by the
		adapter — never payload data. The plaintext token is handed only to
		the ``ceto_order_transfer_requested`` hook; the response is the
		unchanged serialized ``StoreOrder``.
		"""
		return self.transfers.request(
			order_id,
			key,
			requested_by=requested_by,
			requester_email=requester_email,
			description=description,
			update_order_email=update_order_email,
		)

	def cancel_transfer(
		self,
		order_id: str,
		key: PublishableKeyScope,
		*,
		requested_by: str,
	) -> dict[str, Any]:
		"""Cancel the pending ownership transfer of ``order_id``.

		Delegates to the transfer component (:class:`OrderTransfer`): the
		order reference is row-locked before any check, resolution is the
		retrieve path's masked ``404 not_found``, the pending record is
		found regardless of expiry and only its recorded ``requested_by``
		customer may remove it — a missing one, including a replayed
		cancel, is ``400 invalid_data`` and any other caller is ``403
		not_allowed``. Deleting the record destroys its digest-only token;
		nothing in the order lineage is written (Recorded Decision 12) and
		the response is the unchanged serialized ``StoreOrder``.
		``requested_by`` is the authenticated caller's Customer, resolved
		by the adapter — never payload data.
		"""
		return self.transfers.cancel(order_id, key, requested_by=requested_by)
