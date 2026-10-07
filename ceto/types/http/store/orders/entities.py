from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ceto.types.http.store.carts.entities import StoreCartAddress
from ceto.types.http.store.customers.entities import StoreCustomer

#: Pinned ``OrderStatus`` union of ``@medusajs/types@2.21.1``.
OrderStatus = Literal["pending", "completed", "draft", "archived", "canceled", "requires_action"]

#: Pinned ``PaymentStatus`` union of ``@medusajs/types@2.21.1``.
PaymentStatus = Literal[
	"not_paid",
	"awaiting",
	"authorized",
	"partially_authorized",
	"captured",
	"partially_captured",
	"partially_refunded",
	"refunded",
	"canceled",
	"requires_action",
]

#: Pinned ``FulfillmentStatus`` union of ``@medusajs/types@2.21.1``.
FulfillmentStatus = Literal[
	"not_fulfilled",
	"partially_fulfilled",
	"fulfilled",
	"partially_shipped",
	"shipped",
	"partially_delivered",
	"delivered",
	"canceled",
]


class StoreOrderAddress(StoreCartAddress):
	"""Medusa ``StoreOrderAddress`` entity (Phase 6 subset).

	The pinned ``StoreOrderAddress`` of ``@medusajs/types@2.21.1`` carries
	the same address columns Ceto already serializes for carts
	(:class:`StoreCartAddress`): both are the cart-scoped ERPNext ``Address``
	copy the claim/claim-completion flow owns. The subclass exists so order
	payloads carry their own pinned name.
	"""


class StoreOrderLineItem(BaseModel):
	"""Medusa ``StoreOrderLineItem`` shape (Phase 6 subset).

	Mirrors the pinned ``StoreOrderLineItem`` of ``@medusajs/types@2.21.1``
	for the columns the completion serializer derives from the mapped Sales
	Order item and the cart line reference carried over from the completed
	cart. Money fields follow the ``StoreCart`` convention (plain floats, no
	minor units); fields the current Quotation-backed serializer cannot
	populate are omitted until the matching provider exists.
	"""

	id: str
	order_id: str
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


class StoreOrderShippingMethod(BaseModel):
	"""Medusa ``StoreOrderShippingMethod`` shape (Phase 6 subset).

	Mirrors the pinned ``BaseOrderShippingMethod`` columns of
	``@medusajs/types@2.21.1`` that the completion serializer derives from
	the Sales Order's ``Shipping Rule`` charge row — the same row identity
	the cart serializes (see ``docs/carts/field-mapping.md``). The row
	carries no tax allocation, so ``is_tax_inclusive`` is required and false,
	and the row also timestamps the method.
	"""

	id: str
	order_id: str
	shipping_option_id: str | None = None
	name: str
	amount: float = 0
	subtotal: float = 0
	total: float = 0
	tax_total: float = 0
	is_tax_inclusive: bool
	created_at: datetime
	updated_at: datetime


class StoreOrder(BaseModel):
	"""Medusa ``StoreOrder`` shape (Phase 6 subset).

	Mirrors the pinned ``StoreOrder`` of ``@medusajs/types@2.21.1`` for the
	columns the completion serializer can derive from the ERPNext Sales
	Order and the completed cart's ``Ceto Cart Reference``. The summary
	follows the cart reconciliation: the shipping charge and the consumed
	credit deductions are carved out of the tax fields, ``total`` stays the
	ERPNext grand total.

	Deliberately omitted (Recorded Decision, Phase 6): ``display_id`` and
	``custom_display_id`` — Medusa's sequential display numbers have no
	ERPNext equivalent and the public order id is Ceto's own ``order_…``
	id — plus ``version``, ``summary``, ``transactions``,
	``payment_collections`` and ``fulfillments``, which stay omitted until
	the matching provider (payments, fulfillment) exists. The pinned
	``item_discount_total`` / ``shipping_discount_total`` split is omitted
	too: ERPNext carries a single order-level ``discount_amount`` (per-row
	discounts ride the item rows) and gives the Shipping Rule charge no
	discount bucket, so the Medusa item/shipping discount split cannot be
	derived without inventing numbers — ``discount_total`` keeps the
	order-level amount.

	The pinned order's optional ``customer`` relation embeds the same pinned
	``StoreCustomer`` the customers contract serves (verified against the
	published ``HttpTypes`` when the customers surface was pinned, see
	``docs/customers/endpoints.md``): the completed cart's owner resolves
	through the shared identity resolver and its ``Ceto Customer Reference``
	and serializes with the shared ``CustomerSerializer``, so the embedded
	representation is exactly what the customers routes return. The column
	stays ``None`` for guests and for owners without a reference — no
	identity is ever invented — while ``customer_id`` above keeps the
	carts' historical ERPNext Customer-name mapping beside the embedded
	stable ``cus_…`` id (the recorded compatibility deviation, decision 10
	of ``docs/carts/field-mapping.md``).
	"""

	id: str
	region_id: str | None = None
	customer_id: str | None = None
	customer: StoreCustomer | None = None
	sales_channel_id: str | None = None
	email: str | None = None
	currency_code: str
	status: OrderStatus = "pending"
	payment_status: PaymentStatus = "not_paid"
	fulfillment_status: FulfillmentStatus = "not_fulfilled"
	metadata: dict[str, Any] | None = None
	billing_address: StoreOrderAddress | None = None
	shipping_address: StoreOrderAddress | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	items: list[StoreOrderLineItem] = Field(default_factory=list)
	shipping_methods: list[StoreOrderShippingMethod] = Field(default_factory=list)
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
	credit_line_total: float = 0
	shipping_total: float = 0
	shipping_subtotal: float = 0
	shipping_tax_total: float = 0
	original_shipping_total: float = 0
	original_shipping_subtotal: float = 0
	original_shipping_tax_total: float = 0
