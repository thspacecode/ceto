"""Pinned contract manifest for the Medusa Store Product Tag routes.

Source of truth: <https://docs.medusajs.com/api/store/product-tags>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 2 slice 2A pins the contract; a behavior slice registers both routes
on the router and serves them. The manifest is pure Python (no Frappe
imports) so it can drive request validation codegen and be tested
standalone.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/product-tag/store``). The
pinned SDK has **no** product-tag namespace at all (verified against the
published SDK sources), so both routes below must be called with a raw HTTP
client when replicating Medusa client behavior — like the currency and
locale routes.

The pinned 2.21.1 list validator defaults the page to ``offset: 0`` /
``limit: 50`` — verified against the published ``@medusajs/medusa@2.21.1``
sources. The list read model caps one page at
``PRODUCT_TAG_LIST_MAX_LIMIT`` rows (a Ceto decision, not upstream parity).

Tags project the Frappe user tags of the published catalog items,
deduplicated and ordered by value (Recorded Decision 6 in
``docs/catalog/field-mapping.md``).
"""

from dataclasses import dataclass

PRODUCT_TAG_API_SOURCE_URL = "https://docs.medusajs.com/api/store/product-tags"

PRODUCT_TAG_TYPES_PACKAGE = "@medusajs/types"

PRODUCT_TAG_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key middleware and the list
#: validator defaults (page 0/50, no default sort).
PRODUCT_TAG_SERVER_PACKAGE = "@medusajs/medusa"

PRODUCT_TAG_SERVER_VERSION = "2.21.1"

#: Upstream server pagination defaults, pinned by the core product tag query
#: config (``defaultStoreProductTagFields`` / ``listTransformQueryConfig``)
#: and the ``StoreGetProductTagsParams`` validator.
PRODUCT_TAG_LIST_DEFAULT_LIMIT = 50

PRODUCT_TAG_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many tags.
PRODUCT_TAG_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class ProductTagRoute:
	"""One pinned Medusa Store Product Tag route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the
	route; both tag routes pin one.
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


PRODUCT_TAG_ROUTES: tuple[ProductTagRoute, ...] = (
	ProductTagRoute(
		method="GET",
		path="/store/product-tags",
		request_type=None,
		response_type="StoreProductTagListResponse",
		auth="publishable-key",
		sdk_method=None,
		query_type="StoreProductTagListParams",
	),
	ProductTagRoute(
		method="GET",
		path="/store/product-tags/{id}",
		request_type=None,
		response_type="StoreProductTagResponse",
		auth="publishable-key",
		sdk_method=None,
		query_type="StoreProductTagParams",
	),
)
