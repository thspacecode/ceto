from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CartPayload(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	region_id: str | None = None
	email: EmailStr | None = None
	sales_channel_id: str | None = None
	metadata: dict[str, Any] | None = None
	locale: str | None = None


class StoreCartAddressPayload(BaseModel):
	"""Medusa cart address in object form.

	Mirrors the pinned ``HttpTypes`` address payload of
	``@medusajs/types@2.21.1``: every field is optional (Medusa merges the
	object into the current address) and unknown fields are rejected so new
	Medusa fields fail loudly instead of being silently dropped.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	first_name: str | None = None
	last_name: str | None = None
	company: str | None = None
	phone: str | None = None
	address_1: str | None = None
	address_2: str | None = None
	city: str | None = None
	province: str | None = None
	postal_code: str | None = None
	country_code: str | None = None

	@field_validator("country_code")
	@classmethod
	def _validate_country_code(cls, value: str | None) -> str | None:
		if value is not None and len(value) != 2:
			raise ValueError("country_code must be a two-letter ISO 3166-1 alpha-2 code")
		return value.lower() if value else value


class StoreAddCartLineItem(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	variant_id: str = Field(min_length=1)
	quantity: int = Field(gt=0)
	metadata: dict[str, Any] | None = None


class StoreAddCartShippingMethods(BaseModel):
	"""Body of ``POST /store/carts/{id}/shipping-methods``.

	Mirrors ``StoreAddCartShippingMethods`` of the pinned ``HttpTypes`` of
	``@medusajs/types@2.21.1``: a shipping option reference plus optional
	provider data. Unknown fields are rejected so new Medusa fields fail
	loudly instead of being silently dropped.

	The pinned type is a union of a single ``{option_id, data?}`` object and
	an array of them (since 2.16.0); Ceto implements the **single-object**
	member only. The Quotation carries exactly one ``Shipping Rule`` link, so
	an array of methods has no ERPNext target, and the router rejects
	non-object request bodies before payload validation.

	``data`` is accepted for request compatibility only. Ceto's ERPNext
	compatibility field for a cart shipping method is the Quotation's
	``Shipping Rule`` link, which carries no provider payload, so there is no
	field to persist ``data`` in: it is validated and dropped (pinned by the
	route tests).
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	option_id: str = Field(min_length=1)
	data: dict[str, Any] | None = None


class _StoreCartPromoCodesPayload(BaseModel):
	"""Shared ``promo_codes`` body of the Medusa promotions routes.

	Mirrors ``StoreCartAddPromotion`` / ``StoreCartRemovePromotion`` of the
	pinned ``HttpTypes`` of ``@medusajs/types@2.21.1``: a non-empty list of
	promotion code strings. Unknown fields are rejected; blank codes are
	rejected rather than being silently dropped.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	promo_codes: list[str] = Field(min_length=1)

	@field_validator("promo_codes")
	@classmethod
	def _validate_codes(cls, codes: list[str]) -> list[str]:
		if any(not code for code in codes):
			raise ValueError("promo_codes must not contain empty codes")
		return codes


class StoreCartAddPromotion(_StoreCartPromoCodesPayload):
	"""Body of ``POST /store/carts/{id}/promotions``."""


class StoreCartRemovePromotion(_StoreCartPromoCodesPayload):
	"""Body of ``DELETE /store/carts/{id}/promotions``."""


class StoreAddGiftCardToCart(BaseModel):
	"""Body of ``POST /store/carts/{id}/gift-cards``.

	Mirrors the pinned ``StoreAddGiftCardToCart`` of the loyalty plugin
	(``@zjedene-medusa/loyalty-plugin@2.16.2``): a single gift-card code in a
	strict object, so unknown fields are rejected exactly like the plugin's
	``z.strictObject`` validator. The plugin accepts a blank code; Ceto rejects
	it rather than silently ignoring the request (same rule as promo codes).
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	code: str = Field(min_length=1)


class StoreRemoveGiftCardFromCart(BaseModel):
	"""Body of ``DELETE /store/carts/{id}/gift-cards``.

	Mirrors the pinned ``StoreRemoveGiftCardFromCart`` of the loyalty plugin
	(``@zjedene-medusa/loyalty-plugin@2.16.2``): unlike every other cart
	removal route, the pinned removal is a bodyful ``DELETE`` carrying the
	gift-card code to release, in a strict object. Blank codes are rejected.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	code: str = Field(min_length=1)


class StoreAddStoreCreditsToCart(BaseModel):
	"""Body of ``POST /store/carts/{id}/store-credits``.

	Mirrors the pinned ``StoreAddStoreCreditsToCart`` of the loyalty plugin
	(``@zjedene-medusa/loyalty-plugin@2.16.2``): an optional ``amount``. When
	omitted the plugin reserves the customer's whole available balance, so the
	field stays optional; a provided amount must be positive — a credit
	reservation with no value has no ERPNext meaning and would only fake a
	hold.

	Unlike the gift-card routes the plugin validates this body with ``z.object``
	instead of ``z.strictObject``: unknown fields are stripped, not rejected.
	Ceto mirrors that leniency so plugin clients keep working unchanged.
	"""

	model_config = ConfigDict(extra="ignore")

	amount: float | None = Field(default=None, gt=0)


class StoreCalculateCartTaxes(BaseModel):
	"""Body of ``POST /store/carts/{id}/taxes``.

	Mirrors the empty ``StoreCalculateCartTaxes`` interface of the pinned
	``HttpTypes`` of ``@medusajs/types@2.21.1``: the route carries no body
	fields, so any unexpected field is rejected.
	"""

	model_config = ConfigDict(extra="forbid")


class StoreCompleteCart(BaseModel):
	"""Body of ``POST /store/carts/{id}/complete``.

	Mirrors the pinned ``StoreCompleteCart`` interface of the ``HttpTypes``
	of ``@medusajs/types@2.21.1``: only an optional idempotency key. Unknown
	fields are rejected like every other core cart payload.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	idempotency_key: str | None = None


class StoreCreateCart(CartPayload):
	currency_code: str | None = None
	shipping_address: StoreCartAddressPayload | str | None = None
	billing_address: StoreCartAddressPayload | str | None = None
	items: list[StoreAddCartLineItem] | None = None
	promo_codes: list[str] | None = None


class StoreUpdateCart(CartPayload):
	shipping_address: StoreCartAddressPayload | str | None = None
	billing_address: StoreCartAddressPayload | str | None = None
	promo_codes: list[str] | None = None


class StoreUpdateCartLineItem(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	quantity: int = Field(gt=0)
	metadata: dict[str, Any] | None = None
