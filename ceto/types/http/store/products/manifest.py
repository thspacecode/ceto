"""Pinned contract manifest for the Medusa Store product routes.

Sources of truth: <https://docs.medusajs.com/api/store/products>,
<https://docs.medusajs.com/api/store/product-variants> and
<https://docs.medusajs.com/api/store/product-options>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 3 pins the contract for exactly five GET routes; a behavior slice
registers them on the router and serves them. The manifest is pure Python
(no Frappe imports) so it can drive request validation codegen and be
tested standalone. The routes stay unregistered and the README rows stay
untouched until that slice lands.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/product/store``). The
products and product-options pairs are covered by dedicated SDK methods —
``sdk.store.product`` and ``sdk.store.productOption`` (the option namespace
is camelCase and shipped in 2.16.0) — while the pinned SDK has **no**
product-variant namespace at all, so the canonical
``GET /store/product-variants`` list needs a raw HTTP client when
replicating Medusa client behavior (verified against the published SDK
sources).

The pinned 2.21.1 list validators default the pages to ``offset: 0`` with
``limit: 50`` for products, ``limit: 20`` for variants and ``limit: 50``
for options — verified against the published ``@medusajs/medusa@2.21.1``
sources (``createFindParams`` overrides plus the store query configs). The
same sources pin the product routes' server-side ``status: published``
default filter, so the assortment is published-only upstream. The list
read models cap one page at the ``*_LIST_MAX_LIMIT`` rows (a Ceto decision,
not upstream parity).

Upstream also serves ``GET /store/product-variants/{id}`` (since 2.11.2);
it is deliberately out of this slice's pinned inventory — the list route is
the canonical variants surface (products slice decision 5 in
``docs/catalog/products-field-mapping.md``).
"""

from dataclasses import dataclass

PRODUCT_API_SOURCE_URL = "https://docs.medusajs.com/api/store/products"

PRODUCT_VARIANT_API_SOURCE_URL = "https://docs.medusajs.com/api/store/product-variants"

PRODUCT_OPTION_API_SOURCE_URL = "https://docs.medusajs.com/api/store/product-options"

PRODUCT_SDK_PACKAGE = "@medusajs/js-sdk"

PRODUCT_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below (``http/product/store``).
PRODUCT_TYPES_PACKAGE = "@medusajs/types"

PRODUCT_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key boundary, the ``status:
#: published`` default filter on the product routes and the list validator
#: defaults (pages 0/50, 0/20 and 0/50).
PRODUCT_SERVER_PACKAGE = "@medusajs/medusa"

PRODUCT_SERVER_VERSION = "2.21.1"

#: Product methods directly exposed by the pinned SDK version — the
#: ``sdk.store.product`` namespace covers the whole products surface.
PRODUCT_SDK_METHODS = (
	"list",
	"retrieve",
)

#: Product option methods directly exposed by the pinned SDK version — the
#: ``sdk.store.productOption`` namespace (camelCase, shipped in 2.16.0)
#: covers the whole options surface.
PRODUCT_OPTION_SDK_METHODS = (
	"list",
	"retrieve",
)

#: The pinned SDK has no product-variant namespace at all, so there is no
#: variant method surface to pin — the canonical variants list route is
#: called with a raw HTTP client when replicating Medusa client behavior.

#: Upstream server pagination defaults, pinned by the ``StoreGetProductsParams``
#: validator (``createFindParams({ offset: 0, limit: 50 })``) and the store
#: ``listProductQueryConfig``.
PRODUCT_LIST_DEFAULT_LIMIT = 50

PRODUCT_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many products.
PRODUCT_LIST_MAX_LIMIT = 100

#: Upstream server pagination defaults, pinned by the
#: ``StoreProductVariantListParams`` validator (``createFindParams`` with
#: ``offset: 0`` / ``limit: 20``) and the store ``listProductVariantConfig``.
PRODUCT_VARIANT_LIST_DEFAULT_LIMIT = 20

PRODUCT_VARIANT_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity): the variants list read model caps one
#: page at this many variants.
PRODUCT_VARIANT_LIST_MAX_LIMIT = 100

#: Upstream server pagination defaults, pinned by the
#: ``StoreProductOptionsParams`` validator (``createFindParams`` with
#: ``offset: 0`` / ``limit: 50``) and the store ``listProductOptionConfig``.
PRODUCT_OPTION_LIST_DEFAULT_LIMIT = 50

PRODUCT_OPTION_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity): the options list read model caps one
#: page at this many options.
PRODUCT_OPTION_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ProductRoute:
	"""One pinned Medusa Store product-surface route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the
	route; every route below pins one. ``sdk_method`` is ``None`` where the
	pinned SDK exposes no namespace for the route (the variants list).
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


PRODUCT_ROUTES: tuple[ProductRoute, ...] = (
	ProductRoute(
		method="GET",
		path="/store/products",
		request_type=None,
		response_type="StoreProductListResponse",
		auth="publishable-key",
		sdk_method="list",
		query_type="StoreProductListParams",
	),
	ProductRoute(
		method="GET",
		path="/store/products/{id}",
		request_type=None,
		response_type="StoreProductResponse",
		auth="publishable-key",
		sdk_method="retrieve",
		query_type="StoreProductParams",
	),
)

#: Exactly one variants route is pinned — the canonical list
#: (products slice decision 5). The upstream detail route exists but stays
#: out of the pinned inventory.
PRODUCT_VARIANT_ROUTES: tuple[ProductRoute, ...] = (
	ProductRoute(
		method="GET",
		path="/store/product-variants",
		request_type=None,
		response_type="StoreProductVariantListResponse",
		auth="publishable-key",
		sdk_method=None,
		query_type="StoreProductVariantListParams",
	),
)

PRODUCT_OPTION_ROUTES: tuple[ProductRoute, ...] = (
	ProductRoute(
		method="GET",
		path="/store/product-options",
		request_type=None,
		response_type="StoreProductOptionListResponse",
		auth="publishable-key",
		sdk_method="list",
		query_type="StoreProductOptionListParams",
	),
	ProductRoute(
		method="GET",
		path="/store/product-options/{id}",
		request_type=None,
		response_type="StoreProductOptionResponse",
		auth="publishable-key",
		sdk_method="retrieve",
		query_type="StoreProductOptionParams",
	),
)
