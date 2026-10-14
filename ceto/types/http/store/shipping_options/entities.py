"""Pinned shipping-option entity contract.

Mirrors ``http/fulfillment/store`` of ``@medusajs/types@2.21.1`` —
``StoreCartShippingOption`` — for the columns Ceto can derive from ERPNext
``Shipping Rule`` masters. The public option id is the rule name, the same
id the cart surface applies through ``POST /store/carts/{id}/shipping-methods``
(``docs/carts/field-mapping.md``):

- ``id`` / ``name`` / ``price_type`` mirror the pinned required columns that
  survive the projection and are always derivable from the rule master: the
  rule name, the rule ``label``, and the rule's ``calculate_based_on``
  (``Fixed`` rates are ``flat``; ``Net Total`` and ``Net Weight`` rates are
  computed against the cart, ``calculated``).
- ``amount`` and ``calculated_price`` carry the ERP-computed rate: ERPNext
  prices the rule itself (the same charge the applied method books as the
  Quotation's ``Actual`` tax row), so ``amount`` follows the repository
  money convention (plain floats, no minor units) and defaults to the
  itemless baseline 0, while ``calculated_price`` reuses the pinned
  :class:`~ceto.types.http.store.products.StoreCalculatedPrice`. The rate
  resolves against the cart; an unresolvable context serves the honest
  empty value instead of a fabricated one (the cart-methods convention).
- The fulfillment-module columns — ``service_zone_id``,
  ``shipping_profile_id``, ``provider_id``, ``data``, ``metadata``, the
  ``type`` and ``provider`` relations, the stored ``prices`` and
  ``insufficient_inventory`` — have no ERPNext source and are dropped
  entirely, never stubbed (the products-slice projection precedent). The
  list response's ``service_zone.fulfillment_set.location.address``
  expansion has the same fate: both envelopes serve this flat entity.
"""

from typing import Literal

from pydantic import BaseModel

from ceto.types.http.store.products import StoreCalculatedPrice


class StoreCartShippingOption(BaseModel):
	"""Medusa ``StoreCartShippingOption`` shape (Phase 4 subset)."""

	id: str
	name: str
	price_type: Literal["flat", "calculated"]
	amount: float = 0
	calculated_price: StoreCalculatedPrice | None = None
