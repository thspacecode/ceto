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

Everything else upstream accepts is deliberately absent and rejected as an
unknown field (``docs/catalog/products-endpoints.md``): the ``q`` search,
the ``id``/``title``/``handle``/``sku``/``collection_id``/``type_id``/
``tag_id``/``category_id``/``external_id``/``is_giftcard``/``status``/
``sales_channel_id``/``product_id``/``options``/``is_exclusive`` filter
surfaces, the ``created_at``/``updated_at``/``deleted_at`` operator maps,
the ``$and``/``$or`` combinators, the ``order`` sort expressions, the
``fields`` selectors, the nested ``variants`` filter, the pricing-context
keys (``region_id``, ``country_code``, ``province``, ``cart_id`` — cart
publication enforcement is out of scope, products slice decision 6) and
the ``locale`` selector. The projections expose no searchable column and no
selectable surface beyond the pinned entities, and a client must never
receive a page it cannot reproduce.
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
	bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_LIST_DEFAULT_OFFSET, ge=0)


class StoreProductParams(BaseModel):
	"""Query of ``GET /store/products/{id}``.

	The pinned ``StoreProductParams`` is a bare ``SelectParams`` upstream plus
	the pricing-context keys; Ceto serves no ``fields`` selector on the fixed
	projection and prices no product on the read boundary, so the model
	accepts nothing and forbids everything: every key — including a
	``fields`` selector or a ``region_id`` / ``cart_id`` pricing context —
	is refused as ``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")


class StoreProductVariantListParams(BaseModel):
	"""Query of ``GET /store/product-variants``.

	Mirrors the pinned ``StoreProductVariantListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination the
	upstream validator pins (``offset: 0`` / ``limit: 20``). Unknown keys
	are rejected like on every core payload, and the pagination carries the
	Ceto read-model bounds: ``limit`` is the pinned default capped at one
	page's bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_VARIANT_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_VARIANT_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_VARIANT_LIST_DEFAULT_OFFSET, ge=0)


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
