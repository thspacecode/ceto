from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CartPayload(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	region_id: str | None = None
	email: EmailStr | None = None
	sales_channel_id: str | None = None
	metadata: dict[str, Any] | None = None
	locale: str | None = None


class StoreAddCartLineItem(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	variant_id: str = Field(min_length=1)
	quantity: int = Field(gt=0)
	metadata: dict[str, Any] | None = None


class StoreCreateCart(CartPayload):
	currency_code: str | None = None
	shipping_address: dict[str, Any] | str | None = None
	billing_address: dict[str, Any] | str | None = None
	items: list[StoreAddCartLineItem] | None = None
	promo_codes: list[str] | None = None


class StoreUpdateCart(CartPayload):
	shipping_address: dict[str, Any] | str | None = None
	billing_address: dict[str, Any] | str | None = None
	promo_codes: list[str] | None = None


class StoreUpdateCartLineItem(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	quantity: int = Field(gt=0)
	metadata: dict[str, Any] | None = None
