"""Pinned response envelopes of the Medusa Store payment routes.

Mirrors ``StorePaymentProviderListResponse`` (the pinned
``PaginatedResponse`` over ``StorePaymentProvider``: the provider page,
the exact ``count`` of the scoped list and the effective ``offset`` /
``limit``) and ``StorePaymentCollectionResponse`` (the collection under
the ``payment_collection`` key both collection-serving routes return).
"""

from pydantic import BaseModel, Field

from ceto.types.http.store.payments.entities import StorePaymentCollection, StorePaymentProvider


class StorePaymentProviderListResponse(BaseModel):
	"""Response of ``GET /store/payment-providers``."""

	payment_providers: list[StorePaymentProvider] = Field(default_factory=list)
	count: int = 0
	offset: int = 0
	limit: int = 0


class StorePaymentCollectionResponse(BaseModel):
	"""Response of the two collection-serving routes."""

	payment_collection: StorePaymentCollection
