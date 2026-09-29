from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StoreCartAddress(BaseModel):
	"""Medusa ``StoreCartAddress`` entity (pinned baseline fields)."""

	id: str
	customer_id: str | None = None
	company: str | None = None
	first_name: str | None = None
	last_name: str | None = None
	phone: str | None = None
	address_1: str | None = None
	address_2: str | None = None
	city: str | None = None
	province: str | None = None
	postal_code: str | None = None
	country_code: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None


class StoreCartLineItem(BaseModel):
	"""Medusa ``StoreCartLineItem`` shape (Phase 2 subset).

	Money fields mirror the ``StoreCart`` convention (plain floats, no minor
	units); fields the current Quotation-backed serializer cannot populate are
	omitted until the matching provider exists.
	"""

	id: str
	cart_id: str
	title: str | None = None
	product_id: str | None = None
	product_title: str | None = None
	variant_id: str | None = None
	variant_title: str | None = None
	thumbnail: str | None = None
	quantity: int
	requires_shipping: bool = True
	is_discountable: bool = True
	metadata: dict[str, Any] | None = None
	unit_price: float = 0
	original_unit_price: float = 0
	subtotal: float = 0
	total: float = 0
	discount_total: float = 0
	tax_total: float = 0
	created_at: datetime | None = None
	updated_at: datetime | None = None


class StoreCartPromotion(BaseModel):
	"""Medusa ``StoreCart.promotions`` entry (Phase 4 subset).

	Every field is derived from the ERPNext ``Coupon Code`` linked to the
	Quotation; no discount value is invented here (the ERPNext-calculated
	discounts surface in the cart/line money fields).
	"""

	id: str
	code: str
	is_automatic: bool = False


class StoreCart(BaseModel):
	id: str
	region_id: str | None = None
	customer_id: str | None = None
	sales_channel_id: str | None = None
	email: str | None = None
	currency_code: str
	metadata: dict[str, Any] | None = None
	locale: str | None = None
	billing_address: StoreCartAddress | None = None
	shipping_address: StoreCartAddress | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	completed_at: datetime | None = None
	items: list[StoreCartLineItem] = Field(default_factory=list)
	shipping_methods: list[dict[str, Any]] = Field(default_factory=list)
	promotions: list[StoreCartPromotion] = Field(default_factory=list)
	original_item_total: float = 0
	original_item_subtotal: float = 0
	original_item_tax_total: float = 0
	item_total: float = 0
	item_subtotal: float = 0
	item_tax_total: float = 0
	original_total: float = 0
	original_subtotal: float = 0
	original_tax_total: float = 0
	total: float = 0
	subtotal: float = 0
	tax_total: float = 0
	discount_total: float = 0
	discount_tax_total: float = 0
	gift_card_total: float = 0
	gift_card_tax_total: float = 0
	shipping_total: float = 0
	shipping_subtotal: float = 0
	shipping_tax_total: float = 0
	original_shipping_total: float = 0
	original_shipping_subtotal: float = 0
	original_shipping_tax_total: float = 0
