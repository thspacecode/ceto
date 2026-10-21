"""Pinned contract manifest for the Medusa Store Product Category routes.

Source of truth: <https://docs.medusajs.com/api/store/product-categories>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 2 slice 2A pins the contract; a behavior slice registers both routes
on the router and serves them. The manifest is pure Python (no Frappe
imports) so it can drive request validation codegen and be tested
standalone.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/product-category/store``).
Both routes below are covered by a dedicated SDK method — note the SDK
namespace is ``sdk.store.category``, **not** ``productCategory`` (verified
against the published SDK sources), so no route needs a raw HTTP client.

The pinned 2.21.1 list validator defaults the page to ``offset: 0`` /
``limit: 50`` — verified against the published
``@medusajs/medusa@2.21.1`` sources. The list read model caps one page at
``PRODUCT_CATEGORY_LIST_MAX_LIMIT`` rows (a Ceto decision, not upstream
parity).

Categories are the ERPNext ``Item Group`` tree, published only inside the
configured storefront roots (Recorded Decision 1 in
``docs/catalog/field-mapping.md``).
"""

from dataclasses import dataclass

PRODUCT_CATEGORY_API_SOURCE_URL = "https://docs.medusajs.com/api/store/product-categories"

PRODUCT_CATEGORY_SDK_PACKAGE = "@medusajs/js-sdk"

PRODUCT_CATEGORY_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
PRODUCT_CATEGORY_TYPES_PACKAGE = "@medusajs/types"

PRODUCT_CATEGORY_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key middleware and the list
#: validator defaults (page 0/50, no default sort).
PRODUCT_CATEGORY_SERVER_PACKAGE = "@medusajs/medusa"

PRODUCT_CATEGORY_SERVER_VERSION = "2.21.1"

#: Product category methods directly exposed by the pinned SDK version — on
#: the ``sdk.store.category`` namespace — cover the whole categories surface.
PRODUCT_CATEGORY_SDK_METHODS = (
	"list",
	"retrieve",
)

#: Upstream server pagination defaults, pinned by the core product category
#: query config (``defaultStoreProductCategoriesFields`` /
#: ``listTransformQueryConfig``) and the ``StoreGetProductCategoriesParams``
#: validator.
PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT = 50

PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many categories.
PRODUCT_CATEGORY_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ProductCategoryRoute:
	"""One pinned Medusa Store Product Category route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the
	route; both category routes pin one.
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


PRODUCT_CATEGORY_ROUTES: tuple[ProductCategoryRoute, ...] = (
	ProductCategoryRoute(
		method="GET",
		path="/store/product-categories",
		request_type=None,
		response_type="StoreProductCategoryListResponse",
		auth="publishable-key",
		sdk_method="list",
		query_type="StoreProductCategoryListParams",
	),
	ProductCategoryRoute(
		method="GET",
		path="/store/product-categories/{id}",
		request_type=None,
		response_type="StoreProductCategoryResponse",
		auth="publishable-key",
		sdk_method="retrieve",
		query_type="StoreProductCategoryParams",
	),
)
