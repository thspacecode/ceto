"""Pinned query contracts of the Medusa Store product routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreProductListParams`` / ``StoreProductVariantListParams`` /
``StoreProductOptionListParams`` carry the ``FindParams`` pagination the
upstream validators pin (``offset: 0`` with ``limit: 50`` for products and
options, ``limit: 20`` for variants — recorded in the manifest beside the
Ceto read-model page bounds ``*_LIST_MAX_LIMIT``) and ``StoreProductParams``
/ ``StoreProductOptionParams`` are bare ``SelectParams``.

The Ceto read models bound one page (``limit`` capped at the manifest
bound, both numbers non-negative), so a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped.

The pricing foundation accepts exactly one pricing-context key: a strict
``region_id`` on the priced surfaces (the products list, the product
detail and the variants list), resolved through the cart price-list
authority into the served ``calculated_price`` (products slice decision
6). The remaining upstream pricing-context keys — ``country_code``,
``province`` and ``cart_id`` — are refused as unknown fields like every
other unsupported surface.

Everything else upstream accepts is deliberately absent and rejected as an
unknown field (``docs/catalog/products-endpoints.md``): the ``q`` search,
the ``id``/``title``/``handle``/``sku``/``collection_id``/``type_id``/
``tag_id``/``category_id``/``external_id``/``is_giftcard``/``status``/
``sales_channel_id``/``product_id``/``options``/``is_exclusive`` filter
surfaces, the ``created_at``/``updated_at``/``deleted_at`` operator maps,
the ``$and``/``$or`` combinators, the ``order`` sort expressions, the
``fields`` selectors, the nested ``variants`` filter and the ``locale``
selector. The projections expose no searchable column and no selectable
surface beyond the pinned entities, and a client must never receive a page
it cannot reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.products.manifest import (
	PRODUCT_LIST_DEFAULT_LIMIT,
	PRODUCT_LIST_DEFAULT_OFFSET,
	PRODUCT_LIST_MAX_LIMIT,
	PRODUCT_OPTION_LIST_DEFAULT_LIMIT,
	PRODUCT_OPTION_LIST_DEFAULT_OFFSET,
	PRODUCT_OPTION_LIST_MAX_LIMIT,
	PRODUCT_VARIANT_LIST_DEFAULT_LIMIT,
	PRODUCT_VARIANT_LIST_DEFAULT_OFFSET,
	PRODUCT_VARIANT_LIST_MAX_LIMIT,
)


class StoreProductListParams(BaseModel):
	"""Query of ``GET /store/products``.

	Mirrors the pinned ``StoreProductListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination the
	upstream ``StoreGetProductsParams`` validator pins. Unknown keys are
	rejected like on every core payload, and the pagination carries the Ceto
	read-model bounds: ``limit`` is the pinned default capped at one page's
	bulk load, ``offset`` non-negative. ``region_id`` is the one accepted
	pricing-context key (products slice decision 6): a non-empty value
	resolves through the cart price-list authority and prices the page's
	variants, an absent or blank value serves the projection unpriced.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_LIST_DEFAULT_OFFSET, ge=0)
	region_id: str | None = None


class StoreProductParams(BaseModel):
	"""Query of ``GET /store/products/{id}``.

	Mirrors the pinned ``StoreProductParams`` of ``@medusajs/types@2.21.1``
	reduced to the pricing context the detail route serves: Ceto serves no
	``fields`` selector on the fixed projection and no search/filter/sort
	surface, so the model accepts exactly ``region_id`` — the one accepted
	pricing-context key, pricing the detail's variants through the cart
	price-list authority (products slice decision 6) — and forbids
	everything else. Every other key, including ``country_code``,
	``province``, ``cart_id`` and a ``fields`` selector, is refused as
	``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")

	region_id: str | None = None


class StoreProductVariantListParams(BaseModel):
	"""Query of ``GET /store/product-variants``.

	Mirrors the pinned ``StoreProductVariantListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination the
	upstream validator pins (``offset: 0`` / ``limit: 20``). Unknown keys
	are rejected like on every core payload, and the pagination carries the
	Ceto read-model bounds: ``limit`` is the pinned default capped at one
	page's bulk load, ``offset`` non-negative. ``region_id`` is the one
	accepted pricing-context key (products slice decision 6): a non-empty
	value resolves through the cart price-list authority and prices the
	page's variants, an absent or blank value serves the projection
	unpriced.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_VARIANT_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_VARIANT_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_VARIANT_LIST_DEFAULT_OFFSET, ge=0)
	region_id: str | None = None


class StoreProductOptionListParams(BaseModel):
	"""Query of ``GET /store/product-options``.

	Mirrors the pinned ``StoreProductOptionListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination the
	upstream validator pins (``offset: 0`` / ``limit: 50``). Unknown keys
	are rejected like on every core payload, and the pagination carries the
	Ceto read-model bounds: ``limit`` is the pinned default capped at one
	page's bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_OPTION_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_OPTION_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_OPTION_LIST_DEFAULT_OFFSET, ge=0)


class StoreProductOptionParams(BaseModel):
	"""Query of ``GET /store/product-options/{id}``.

	The pinned ``StoreProductOptionParams`` is a bare ``SelectParams``
	upstream; Ceto serves no ``fields`` selector on the fixed projection yet,
	so the model accepts nothing and forbids everything: every key —
	including a ``fields`` selector the fixed projection never applies — is
	refused as ``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
