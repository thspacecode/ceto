from datetime import datetime
from typing import Any, Literal

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


class StoreCartGiftCard(BaseModel):
	"""Medusa ``StoreCart.gift_cards`` entry (Phase 5 subset).

	Pinned to the loyalty plugin's cart extension
	(``@zjedene-medusa/loyalty-plugin@2.16.2``), whose applied gift cards
	carry exactly the ``code``. Ceto stores gift-card codes hash-only with a
	display hint, so the serialized ``code`` is that hint: clients remove an
	applied gift card by resubmitting the original code, not the hint.
	"""

	code: str


class StoreCartCreditLine(BaseModel):
	"""Medusa ``StoreCart.credit_lines`` entry (Phase 5 subset).

	Mirrors the core ``CartCreditLineDTO`` of the pinned ``HttpTypes`` of
	``@medusajs/types@2.21.1`` for the columns Ceto can derive from its own
	reservation records; ``raw_amount`` is omitted like every other money
	field (plain floats, no minor units). ``reference`` carries the two
	origin models the loyalty plugin produces.
	"""

	id: str
	cart_id: str
	amount: float = 0
	reference: Literal["gift-card", "store-credit"]
	reference_id: str
	metadata: dict[str, Any] | None = None
	created_at: datetime
	updated_at: datetime


class StoreCartShippingMethod(BaseModel):
	"""Medusa ``StoreCartShippingMethod`` shape (Phase 4 subset).

	Fields mirror the pinned ``HttpTypes`` of ``@medusajs/types@2.21.1`` for
	the columns Ceto can derive from ERPNext (``Shipping Rule`` plus Quotation
	shipping tax rows, see ``docs/carts/field-mapping.md``); fields the
	current serializer cannot populate are omitted until the matching
	provider exists. Money fields follow the ``StoreCart`` convention (plain
	floats, no minor units).

	``is_tax_inclusive``, ``created_at`` and ``updated_at`` are required by
	the pinned type and always derivable: the method is the ERPNext ``Actual``
	shipping tax row, which carries no tax allocation (tax-exclusive amount)
	plus its own ``creation``/``modified`` timestamps.
	"""

	id: str
	cart_id: str
	shipping_option_id: str | None = None
	name: str
	amount: float = 0
	subtotal: float = 0
	total: float = 0
	tax_total: float = 0
	is_tax_inclusive: bool
	created_at: datetime
	updated_at: datetime


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
	shipping_methods: list[StoreCartShippingMethod] = Field(default_factory=list)
	promotions: list[StoreCartPromotion] = Field(default_factory=list)
	gift_cards: list[StoreCartGiftCard] = Field(default_factory=list)
	credit_lines: list[StoreCartCreditLine] = Field(default_factory=list)
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
