"""Pinned query contracts of the Medusa Store payment-provider list route.

Mirrors the pinned ``StoreGetPaymentProvidersParams`` of
``@medusajs/types@2.21.1`` as verified against the lockstep server
validator (``createFindParams({limit: 20, offset: 0})`` merged with the
required ``region_id``): the route refuses the request without a region
and paginates with the upstream defaults. ``fields``/``order`` and every
other ``FindParams`` column are deliberately absent and rejected as
unknown keys — the provider entity is an ``id`` only, so there is nothing
to select or sort; a strict query keeps that pinned.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.payments.manifest import (
	PAYMENT_PROVIDER_LIST_DEFAULT_LIMIT,
	PAYMENT_PROVIDER_LIST_DEFAULT_OFFSET,
)


class StoreGetPaymentProvidersParams(BaseModel):
	"""Query params of ``GET /store/payment-providers``."""

	model_config = ConfigDict(extra="forbid")

	region_id: str = Field(min_length=1)
	limit: int = Field(default=PAYMENT_PROVIDER_LIST_DEFAULT_LIMIT, ge=0)
	offset: int = Field(default=PAYMENT_PROVIDER_LIST_DEFAULT_OFFSET, ge=0)
