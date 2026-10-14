"""Pinned response envelopes of the Medusa Store shipping-option routes.

Mirrors the pinned response types of ``@medusajs/types@2.21.1``: the list
responds the exact non-paginated ``{shipping_options}`` body of the pinned
2.21.1 list handler — the pinned ``StoreShippingOptionListResponse`` carries
no ``count``/``offset``/``limit`` and none may grow silently — and the
calculate route responds ``{shipping_option: StoreCartShippingOption}``.
Both carry the same flat Ceto projection: the pinned list member expands
``service_zone.fulfillment_set.location.address``, a fulfillment-module
surface with no ERPNext source, so the ``WithServiceZone`` distinction
collapses (see the entity contract).
"""

from pydantic import BaseModel

from ceto.types.http.store.shipping_options.entities import StoreCartShippingOption


class StoreShippingOptionResponse(BaseModel):
	"""Pinned ``StoreShippingOptionResponse`` of ``@medusajs/types@2.21.1``."""

	shipping_option: StoreCartShippingOption


class StoreShippingOptionListResponse(BaseModel):
	"""Pinned ``StoreShippingOptionListResponse`` of ``@medusajs/types@2.21.1``."""

	shipping_options: list[StoreCartShippingOption]
