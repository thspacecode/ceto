"""Pinned request body of the Medusa Store shipping-option routes.

Mirrors ``StoreCalculateShippingOptionPrice`` of ``@medusajs/types@2.21.1``
— the only bodyful shipping-option route. The pinned upstream validator
strips unknown keys; Ceto rejects them like every core payload so new
Medusa fields fail loudly instead of being silently dropped.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StoreCalculateShippingOptionPrice(BaseModel):
	"""Body of ``POST /store/shipping-options/{id}/calculate``.

	Mirrors the pinned ``StoreCalculateShippingOptionPrice`` of
	``@medusajs/types@2.21.1``: the cart to calculate the price for plus
	optional provider data. ``data`` is accepted for request compatibility
	only — the same seam as the cart shipping-methods body: Ceto's
	compatibility field for a shipping option is the ERPNext ``Shipping
	Rule`` master, which carries no provider payload, so ``data`` is
	validated and dropped (pinned by the route tests when the behavior
	slice lands).
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	cart_id: str = Field(min_length=1)
	data: dict[str, Any] | None = None
