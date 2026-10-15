from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

#: Pinned ``BasePaymentCollectionStatus`` union of ``@medusajs/types@2.21.1``.
PaymentCollectionStatus = Literal[
	"not_paid",
	"awaiting",
	"authorized",
	"partially_authorized",
	"canceled",
	"completed",
	"failed",
]

#: Pinned ``BasePaymentSessionStatus`` union of ``@medusajs/types@2.21.1``.
PaymentSessionStatus = Literal[
	"pending",
	"pending_authorization",
	"authorized",
	"captured",
	"requires_more",
	"error",
	"canceled",
]


class StorePaymentProvider(BaseModel):
	"""Medusa ``StorePaymentProvider`` entity (pinned baseline fields).

	The pinned ``StorePaymentProvider`` of ``@medusajs/types@2.21.1``
	carries exactly the ``id`` — Medusa's provider registry answers "which
	providers exist for this region" with bare ids only. Ceto mirrors that:
	the id is the whole provider identity the store API exposes (see the
	Ceto provider registry in :mod:`ceto.services.payments.providers` for
	where the ids resolve behind the scenes).
	"""

	id: str


class StorePaymentSession(BaseModel):
	"""Medusa ``StorePaymentSession`` shape (Phase 5 subset).

	Mirrors the pinned ``BasePaymentSession`` of ``@medusajs/types@2.21.1``
	for the columns Ceto persists on ``Ceto Payment Session``: identity,
	the payable snapshot (``amount`` + ``currency_code``) idempotent session
	creation keys on, the ``provider_id`` that selected it, the provider's
	own ``data`` payload and the pinned ``status``. Money fields follow the
	``StoreCart`` convention (plain floats, no minor units).

	The pinned type's optional ``payment_collection`` / ``payment``
	relations are omitted: Ceto serves sessions embedded in their payment
	collection, never the other way round, and no Ceto surface produces a
	captured ``payment`` entity yet.
	"""

	id: str
	amount: float = 0
	currency_code: str
	provider_id: str
	data: dict[str, Any] = Field(default_factory=dict)
	context: dict[str, Any] | None = None
	status: PaymentSessionStatus
	authorized_at: datetime | None = None


class StorePaymentCollection(BaseModel):
	"""Medusa ``StorePaymentCollection`` shape (Phase 5 subset).

	Mirrors the pinned ``StorePaymentCollection`` of
	``@medusajs/types@2.21.1`` for the columns Ceto persists on
	``Ceto Payment Collection`` and can derive from the cart: identity,
	currency, the cart total it collects, the pinned ``status`` and the
	embedded ``payment_sessions`` / ``payment_providers`` relations. Money
	fields follow the ``StoreCart`` convention (plain floats, no minor
	units); ``payments`` and the per-collection ``metadata`` are omitted
	until a capture/refund provider exists.
	"""

	id: str
	currency_code: str
	amount: float = 0
	authorized_amount: float | None = None
	captured_amount: float | None = None
	refunded_amount: float | None = None
	completed_at: datetime | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	status: PaymentCollectionStatus = "not_paid"
	payment_providers: list[StorePaymentProvider] = Field(default_factory=list)
	payment_sessions: list[StorePaymentSession] = Field(default_factory=list)
