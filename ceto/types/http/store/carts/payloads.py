from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr


class CartPayload(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	region_id: str | None = None
	email: EmailStr | None = None
	sales_channel_id: str | None = None
	metadata: dict[str, Any] | None = None
	locale: str | None = None


class StoreCreateCart(CartPayload):
	currency_code: str | None = None
	shipping_address: dict[str, Any] | str | None = None
	billing_address: dict[str, Any] | str | None = None
	items: list[dict[str, Any]] | None = None
	promo_codes: list[str] | None = None


class StoreUpdateCart(CartPayload):
	shipping_address: dict[str, Any] | str | None = None
	billing_address: dict[str, Any] | str | None = None
	promo_codes: list[str] | None = None
