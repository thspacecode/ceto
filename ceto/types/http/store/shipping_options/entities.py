"""Pinned shipping-option entity contract.

Mirrors ``http/fulfillment/store`` of ``@medusajs/types@2.21.1`` —
``StoreCartShippingOption`` — for the columns Ceto can derive from ERPNext
``Shipping Rule`` masters and the cart they are listed for:

- ``id`` is the opaque, stable option token
  ``so_<base64url(provider_id + ':' + option_key)>`` — the provider id
  joined with the option key and encoded URL-safe. It is never the raw
  ``Shipping Rule`` name; the encoder belongs to the behavior slice (the
  products-slice id-encoder precedent). The legacy raw rule names stay
  accepted only by the existing cart apply
  (``POST /store/carts/{id}/shipping-methods``,
  ``docs/carts/field-mapping.md``) — this surface never serves them.
- ``name`` / ``price_type`` mirror the pinned required columns derivable
  from the rule master: the rule ``label`` and the pinned
  ``flat``/``calculated`` union. Built-in rules always serve ``flat``:
  every option is a deterministic cart-specific quote — the rule rate
  resolved for this cart — not a stored list price.
- ``provider`` mirrors the pinned ``StoreFulfillmentProvider`` relation
  reduced to the provider-neutral columns the contract needs:
  ``{id, is_enabled}`` of the option's provider — the built-in provider
  for ERPNext rules, enabled by definition (its rules would not serve
  otherwise).
- ``amount`` / ``is_tax_inclusive`` / ``calculated_price`` carry the
  ERP-computed rate: ERPNext prices the rule itself (the same charge the
  applied method books as the Quotation's ``Actual`` tax row), so
  ``amount`` follows the repository money convention (plain floats, no
  minor units) and defaults to the itemless baseline 0, while
  ``is_tax_inclusive`` is ``False`` — the Selling charge row carries no
  tax allocation (the cart shipping-method projection).
  ``calculated_price`` is the shipping-specific subset below, not the
  products pricing model, whose all-optional pricing-module columns would
  serve nulls a shipping quote can always fill. The rate resolves against
  the cart; an unresolvable context serves the honest empty value instead
  of a fabricated one (the cart-methods convention).
- ``data`` / ``metadata`` stay pinned columns of the upstream entity,
  nullable with no ERPNext source: they are served ``null`` and never
  fabricated.
- The remaining fulfillment-module columns — ``service_zone_id``,
  ``shipping_profile_id``, the ``type`` relation, the stored ``prices``
  and ``insufficient_inventory`` — have no ERPNext source and are dropped
  entirely, never stubbed (the products-slice projection precedent). The
  list response's ``service_zone.fulfillment_set.location.address``
  expansion has the same fate: both envelopes serve this same entity.
"""

from typing import Any, Literal

from pydantic import BaseModel


class StoreShippingOptionProvider(BaseModel):
	"""Medusa ``StoreFulfillmentProvider`` shape (Phase 4 subset)."""

	id: str
	is_enabled: bool


class StoreShippingOptionCalculatedPrice(BaseModel):
	"""Shipping-specific ``StoreCalculatedPrice`` subset.

	Mirrors the pinned calculated-price object of ``@medusajs/types@2.21.1``
	for the four columns the shipping projection derives from the cart.
	Every column is required — a shipping quote resolves against the cart,
	money as plain floats (the repository convention) — so when no quote
	resolves, ``calculated_price`` itself stays ``None`` (the entity
	default) instead of a zero-filled subset.
	"""

	calculated_amount: float
	original_amount: float
	currency_code: str
	is_calculated_price_tax_inclusive: bool


class StoreCartShippingOption(BaseModel):
	"""Medusa ``StoreCartShippingOption`` shape (Phase 4 subset)."""

	id: str
	name: str
	price_type: Literal["flat", "calculated"]
	provider: StoreShippingOptionProvider
	amount: float = 0
	is_tax_inclusive: bool = False
	calculated_price: StoreShippingOptionCalculatedPrice | None = None
	data: dict[str, Any] | None = None
	metadata: dict[str, Any] | None = None
