"""Pinned request payloads of the Medusa Store payment routes.

Mirrors the request bodies of ``@medusajs/types@2.21.1`` (``StoreCreatePaymentCollection``
and ``StoreInitializePaymentSession``, the alias ``StoreCreatePaymentSession``
validates under the pinned server release): strict objects whose unknown
fields are rejected so new Medusa fields fail loudly instead of being
silently dropped. The optional ``data`` of the session payload is the
provider's own payment-method input — opaque to Ceto, forwarded to the
resolved provider backend (paygi's PCI-safe ``payment_method`` mapping).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StoreCreatePaymentCollection(BaseModel):
	"""Body of ``POST /store/payment-collections``.

	The pinned payload carries exactly the cart reference; the collection's
	amount and currency are always derived server-side from the cart's
	current payable, never from the request.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	cart_id: str = Field(min_length=1)


class StoreInitializePaymentSession(BaseModel):
	"""Body of ``POST /store/payment-collections/{id}/payment-sessions``.

	``provider_id`` is the pinned ``StorePaymentProvider`` id (``pp_…``);
	``data`` is the optional provider payload (a payment-method token, for
	example) passed through to the provider backend verbatim.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	provider_id: str = Field(min_length=1)
	data: dict[str, Any] | None = None
