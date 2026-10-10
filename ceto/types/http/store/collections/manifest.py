"""Pinned contract manifest for the Medusa Store Collection routes.

Source of truth: <https://docs.medusajs.com/api/store/collections>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 2 slice 2A pins the contract; a behavior slice registers both routes
on the router and serves them. The manifest is pure Python (no Frappe
imports) so it can drive request validation codegen and be tested
standalone.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/collection/store``). Both
routes below are covered by a dedicated SDK method on
``sdk.store.collection`` (verified against the published SDK sources), so
no route needs a raw HTTP client.

The pinned 2.21.1 list validator defaults the page to ``offset: 0`` /
``limit: 10`` and the sort to ``-created_at`` (creation desc) — verified
against the published ``@medusajs/medusa@2.21.1`` sources. The list read
model caps one page at ``COLLECTION_LIST_MAX_LIMIT`` rows (a Ceto decision,
not upstream parity).

Collections are Ceto-stored catalog records (Recorded Decision 2 in
``docs/catalog/field-mapping.md``): handles unique, ids minted.
"""

from dataclasses import dataclass

COLLECTION_API_SOURCE_URL = "https://docs.medusajs.com/api/store/collections"

COLLECTION_SDK_PACKAGE = "@medusajs/js-sdk"

COLLECTION_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
COLLECTION_TYPES_PACKAGE = "@medusajs/types"

COLLECTION_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key middleware and the list
#: validator defaults (page 0/10, default sort ``-created_at``).
COLLECTION_SERVER_PACKAGE = "@medusajs/medusa"

COLLECTION_SERVER_VERSION = "2.21.1"

#: Collection methods directly exposed by the pinned SDK version — the SDK
#: covers the whole collections surface.
COLLECTION_SDK_METHODS = (
	"list",
	"retrieve",
)

#: Upstream server pagination defaults, pinned by the core collection query
#: config (``defaultStoreCollectionFields`` / ``listTransformQueryConfig``)
#: and the ``StoreGetCollectionsParams`` validator.
COLLECTION_LIST_DEFAULT_LIMIT = 10

COLLECTION_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many collections.
COLLECTION_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class CollectionRoute:
	"""One pinned Medusa Store Collection route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the
	route; both collection routes pin one.
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


COLLECTION_ROUTES: tuple[CollectionRoute, ...] = (
	CollectionRoute(
		method="GET",
		path="/store/collections",
		request_type=None,
		response_type="StoreCollectionListResponse",
		auth="publishable-key",
		sdk_method="list",
		query_type="StoreCollectionListParams",
	),
	CollectionRoute(
		method="GET",
		path="/store/collections/{id}",
		request_type=None,
		response_type="StoreCollectionResponse",
		auth="publishable-key",
		sdk_method="retrieve",
		query_type="StoreCollectionParams",
	),
)
