"""Pinned transfer request bodies of the Medusa Store Order routes.

Only the three bodies confirmed by the pinned ``HttpTypes`` of
``@medusajs/types@2.21.1``: the transfer request carries ``description`` /
``update_order_email`` and — deliberately — **no recipient identifier** (the
authenticated customer requests ownership for themselves; the pending
transfer records that requesting customer, see
``docs/orders/field-mapping.md``), and accept and decline carry the
single-use ``token`` received by email — never returned by any Ceto
response. ``POST …/transfer/cancel`` carries no body at all (pinned
``request_type: None`` in the manifest), so it defines no payload.
"""

from pydantic import BaseModel, ConfigDict, Field


class StoreRequestOrderTransfer(BaseModel):
	"""Body of ``POST /store/orders/{id}/transfer/request``.

	Mirrors the pinned ``StoreRequestOrderTransfer`` of
	``@medusajs/types@2.21.1``: an optional description of the request and
	the ``update_order_email`` flag applied at acceptance. Unknown fields are
	rejected so no recipient identifier can sneak in — upstream pins none.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	description: str | None = None
	update_order_email: bool | None = None


class StoreAcceptOrderTransfer(BaseModel):
	"""Body of ``POST /store/orders/{id}/transfer/accept``.

	Mirrors the pinned ``StoreAcceptOrderTransfer`` of
	``@medusajs/types@2.21.1``: the transfer token received in the email
	notification. Ceto persists only its digest and never returns it.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	token: str = Field(min_length=1)


class StoreDeclineOrderTransfer(BaseModel):
	"""Body of ``POST /store/orders/{id}/transfer/decline``.

	Mirrors the pinned ``StoreDeclineOrderTransfer`` of
	``@medusajs/types@2.21.1``: the same token shape as acceptance (the
	pinned core validator carries it under the
	``StoreDeclineOrderTransferRequest`` alias).
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	token: str = Field(min_length=1)
