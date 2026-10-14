"""Pinned product-surface entity contracts.

Mirrors ``http/product/store`` of ``@medusajs/types@2.21.1`` —
``StoreProduct``, ``StoreProductVariant``, ``StoreProductOption``,
``StoreProductOptionValue`` and ``StoreProductImage`` — for the columns
Ceto projects from the published assortment
(``docs/catalog/products-field-mapping.md``):

- ``StoreProduct`` keeps the pinned required trio ``id`` / ``title`` /
  ``handle`` mandatory; every other column stays optional. The embedded
  relations reuse the already-pinned taxonomy entities: ``collection`` is a
  :class:`~ceto.types.http.store.collections.StoreCollection`,
  ``categories`` are :class:`~ceto.types.http.store.product_categories.StoreProductCategory`
  projections (products slice decisions 1 and 3), ``type`` is a
  :class:`~ceto.types.http.store.product_types.StoreProductType` and
  ``tags`` are :class:`~ceto.types.http.store.product_tags.StoreProductTag`
  projections. ``collection_id`` / ``collection`` and ``type_id`` / ``type``
  stay optional and unpopulated until the Ceto-owned item links land
  (products slice decision 4).
- ``StoreProductVariant.id`` is the exact ERPNext ``Item`` code — never
  minted, never transformed (products slice decision 2). The variant
  carries no fabricated commerce flags: ``is_giftcard``, ``discountable``,
  ``manage_inventory``, ``allow_backorder``, dimensions, weights and the
  codes ERPNext does not carry stay ``None`` until a real source exists.
- ``calculated_price`` carries the region-aware price projection of the
  pricing foundation (products slice decision 6): a
  :class:`StoreCalculatedPrice` resolved through the cart price-list
  authority when the caller presents a ``region_id``, ``None`` otherwise.
  ``inventory_quantity`` stays dropped from the projection model entirely:
  inventory is out of scope and Ceto does not stub contracts that do not
  exist yet.
- ``StoreProduct.status`` mirrors the pinned ``ProductStatus`` union
  (``draft`` / ``proposed`` / ``published`` / ``rejected``) but stays
  optional: the store routes pin ``status: published`` server-side
  upstream, so publication is a projection decision, never a served flag.
- ``created_at`` / ``updated_at`` stay optional in every contract like the
  taxonomy slices: the behavior slice serves real record timestamps or
  none (Recorded Decision 8 in ``docs/catalog/field-mapping.md``), never
  fabricated ones.
- ``deleted_at`` stays optional and is never populated: the catalog layer
  deletes hard, there is no soft-delete tombstone.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from ceto.types.http.store.collections import StoreCollection
from ceto.types.http.store.product_categories import StoreProductCategory
from ceto.types.http.store.product_tags import StoreProductTag
from ceto.types.http.store.product_types import StoreProductType


class StoreProductImage(BaseModel):
	"""Medusa ``StoreProductImage`` shape (Phase 3 subset)."""

	id: str
	url: str
	rank: int | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None


class StoreProductOptionValue(BaseModel):
	"""Medusa ``StoreProductOptionValue`` shape (Phase 3 subset)."""

	id: str
	value: str
	rank: int | None = None
	option_id: str | None = None
	option: StoreProductOption | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None


class StoreCalculatedPrice(BaseModel):
	"""Medusa ``CalculatedPriceSet`` shape (Ceto pricing subset).

	Mirrors the pinned calculated-price object of ``@medusajs/types@2.21.1``
	for the columns the region-aware pricing foundation can derive from the
	cart price-list authority. ``raw_calculated_amount`` /
	``raw_original_amount`` and the pricing-module ``id`` are dropped like
	every other money field (plain floats, no minor units — the repository
	money convention), and the nested price-list detail objects carry no
	served source, so they stay out of the contract instead of stubbed.
	"""

	is_calculated_price_price_list: bool | None = None
	is_calculated_price_tax_inclusive: bool | None = None
	calculated_amount: float | None = None
	is_original_price_price_list: bool | None = None
	is_original_price_tax_inclusive: bool | None = None
	original_amount: float | None = None
	currency_code: str | None = None
	is_calculated_price_promotion: bool | None = None


class StoreProductVariant(BaseModel):
	"""Medusa ``StoreProductVariant`` shape (Phase 3 subset)."""

	id: str
	title: str | None = None
	sku: str | None = None
	barcode: str | None = None
	ean: str | None = None
	upc: str | None = None
	thumbnail: str | None = None
	images: list[StoreProductImage] = []
	allow_backorder: bool | None = None
	manage_inventory: bool | None = None
	variant_rank: int | None = None
	product_id: str | None = None
	product: StoreProduct | None = None
	options: list[StoreProductOptionValue] = []
	calculated_price: StoreCalculatedPrice | None = None
	hs_code: str | None = None
	origin_country: str | None = None
	mid_code: str | None = None
	material: str | None = None
	weight: float | None = None
	length: float | None = None
	height: float | None = None
	width: float | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None


class StoreProductOption(BaseModel):
	"""Medusa ``StoreProductOption`` shape (Phase 3 subset)."""

	id: str
	title: str
	is_exclusive: bool | None = None
	product: StoreProduct | None = None
	values: list[StoreProductOptionValue] = []
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None


class StoreProduct(BaseModel):
	"""Medusa ``StoreProduct`` shape (Phase 3 subset)."""

	id: str
	title: str
	handle: str
	subtitle: str | None = None
	description: str | None = None
	is_giftcard: bool | None = None
	discountable: bool | None = None
	status: str | None = None
	thumbnail: str | None = None
	collection_id: str | None = None
	collection: StoreCollection | None = None
	type_id: str | None = None
	type: StoreProductType | None = None
	categories: list[StoreProductCategory] = []
	tags: list[StoreProductTag] = []
	variants: list[StoreProductVariant] = []
	options: list[StoreProductOption] = []
	images: list[StoreProductImage] = []
	external_id: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
