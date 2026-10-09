"""Pinned contract manifest for the Medusa Store Region routes.

Source of truth: <https://docs.medusajs.com/api/store/regions>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 1 slice A pins the contract only — no region handler is implemented
here and no route is registered on the router. The manifest is pure Python
(no Frappe imports) so it can drive request validation codegen and be tested
standalone.

Request/response type names follow the official ``HttpTypes`` published in
``@medusajs/types@2.21.1`` (``http/region/store``). Both list routes below
are covered by a dedicated SDK method on ``sdk.store.region`` (verified
against the published SDK sources), so no route needs a raw HTTP client.

The pinned 2.21.1 list validator defaults the page to ``offset: 0`` /
``limit: 20``; the list read model caps one page at
``REGION_LIST_MAX_LIMIT`` rows (a Ceto decision, not upstream parity).
"""

from dataclasses import dataclass

REGION_API_SOURCE_URL = "https://docs.medusajs.com/api/store/regions"

REGION_SDK_PACKAGE = "@medusajs/js-sdk"

REGION_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
REGION_TYPES_PACKAGE = "@medusajs/types"

REGION_TYPES_VERSION = "2.21.1"

#: Region methods directly exposed by the pinned SDK version — the SDK covers
#: the whole regions surface.
REGION_SDK_METHODS = (
	"list",
	"retrieve",
)

#: Upstream server pagination defaults, pinned by the core region query config
#: (``defaultStoreRegionFields`` / ``listTransformQueryConfig``).
REGION_LIST_DEFAULT_LIMIT = 20

REGION_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many regions.
REGION_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class RegionRoute:
	"""One pinned Medusa Store Region route contract."""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None


REGION_ROUTES: tuple[RegionRoute, ...] = (
	RegionRoute(
		method="GET",
		path="/store/regions",
		request_type=None,
		response_type="StoreRegionListResponse",
		auth="publishable-key",
		sdk_method="list",
	),
	RegionRoute(
		method="GET",
		path="/store/regions/{id}",
		request_type=None,
		response_type="StoreRegionResponse",
		auth="publishable-key",
		sdk_method="retrieve",
	),
)
