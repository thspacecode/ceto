"""Pinned contract manifest for the Medusa Store shipping-option routes.

Sources of truth: <https://docs.medusajs.com/api/store/shipping-options>
(list-shipping-options-for-cart and calculate-shipping-option-price).
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 4 slice 1 pins the contract only — no shipping-option handler is
implemented here. The manifest is pure Python (no Frappe imports) so it can
drive request validation codegen and be tested standalone. The routes stay
unregistered and the README rows stay ⚪️ until the behavior slice lands.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/shipping-option/store``).
Both routes are covered by dedicated SDK methods — the pinned SDK exposes
them under ``sdk.store.fulfillment`` (``listCartOptions`` and ``calculate``),
not under a ``shippingOption`` namespace (verified against the published SDK
sources).

The pinned 2.21.1 list validator (``StoreGetShippingOptions``) requires
``cart_id`` and defaults ``offset: 0`` with ``limit: 20`` — but the pinned
list route ignores the page: it resolves the whole cart-scoped option set
and the pinned ``StoreShippingOptionListResponse`` carries no ``count`` /
``offset`` / ``limit`` at all. The pagination keys are dead upstream
parameters, so the defaults are recorded here as upstream facts and the
Ceto read model refuses the keys instead of serving a pagination the
envelope cannot carry (hence no ``*_LIST_MAX_LIMIT`` page bound).
"""

from dataclasses import dataclass

SHIPPING_OPTION_API_SOURCE_URL = "https://docs.medusajs.com/api/store/shipping-options"

SHIPPING_OPTION_SDK_PACKAGE = "@medusajs/js-sdk"

SHIPPING_OPTION_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below
#: (``http/shipping-option/store`` plus ``http/fulfillment/store``).
SHIPPING_OPTION_TYPES_PACKAGE = "@medusajs/types"

SHIPPING_OPTION_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key boundary (no customer
#: authentication middleware on either route), the required ``cart_id`` on
#: both surfaces and the list validator defaults (page 0/20) the route then
#: ignores.
SHIPPING_OPTION_SERVER_PACKAGE = "@medusajs/medusa"

SHIPPING_OPTION_SERVER_VERSION = "2.21.1"

#: Shipping-option methods directly exposed by the pinned SDK version — the
#: ``sdk.store.fulfillment`` namespace covers the whole surface.
SHIPPING_OPTION_SDK_METHODS = (
	"listCartOptions",
	"calculate",
)

#: Upstream list-validator pagination defaults, pinned by the
#: ``StoreGetShippingOptions`` validator (``createFindParams({ offset: 0,
#: limit: 20 })``). The pinned list route never reads them — it responds the
#: non-paginated ``StoreShippingOptionListResponse`` — so they are recorded
#: here as upstream facts only; the Ceto read model refuses the dead keys.
SHIPPING_OPTION_LIST_DEFAULT_LIMIT = 20

SHIPPING_OPTION_LIST_DEFAULT_OFFSET = 0


@dataclass(frozen=True, slots=True)
class ShippingOptionRoute:
	"""One pinned Medusa Store shipping-option route contract.

	``query_type`` names the query contract the route validates. The
	calculate query is a bare ``SelectParams`` upstream — the pinned
	``HttpTypes`` publish no named type for it and the pinned SDK sends no
	query — so the manifest pins the Ceto-side name
	(:class:`~ceto.types.http.store.shipping_options.StoreShippingOptionCalculateParams`,
	an accept-nothing model).
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


SHIPPING_OPTION_ROUTES: tuple[ShippingOptionRoute, ...] = (
	ShippingOptionRoute(
		method="GET",
		path="/store/shipping-options",
		request_type=None,
		response_type="StoreShippingOptionListResponse",
		auth="publishable-key",
		sdk_method="listCartOptions",
		query_type="StoreGetShippingOptionList",
	),
	ShippingOptionRoute(
		method="POST",
		path="/store/shipping-options/{id}/calculate",
		request_type="StoreCalculateShippingOptionPrice",
		response_type="StoreShippingOptionResponse",
		auth="publishable-key",
		sdk_method="calculate",
		query_type="StoreShippingOptionCalculateParams",
	),
)
