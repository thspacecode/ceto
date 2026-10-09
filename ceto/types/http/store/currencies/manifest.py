"""Pinned contract manifest for the Medusa Store Currency routes.

Source of truth: <https://docs.medusajs.com/api/store/currencies>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 1 slice A pinned the contract; slice B registers both routes on the
router (``ceto.api.store.currencies``) and serves them from
``ceto.services.reference.currencies``. The manifest is pure Python (no
Frappe imports) so it can drive request validation codegen and be tested
standalone.

Request/response/query type names follow the official ``HttpTypes``
published in ``@medusajs/types@2.21.1`` (``http/currency/store``). The
pinned SDK has **no** currency namespace at all (verified against the
published SDK sources), so both routes below must be called with a raw HTTP
client when replicating Medusa client behavior — like the cart ``taxes``
routes.

The pinned 2.21.1 list validator defaults the page to ``offset: 0`` /
``limit: 50``; the list read model caps one page at
``CURRENCY_LIST_MAX_LIMIT`` rows (a Ceto decision, not upstream parity).
Ceto's currency list is deliberately scoped to the currencies referenced by
its valid configured commerce regions — never the full ERPNext currency
table (``docs/reference-data/field-mapping.md``).
"""

from dataclasses import dataclass

CURRENCY_API_SOURCE_URL = "https://docs.medusajs.com/api/store/currencies"

CURRENCY_TYPES_PACKAGE = "@medusajs/types"

CURRENCY_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the publishable-key middleware and the list
#: validator defaults for the currency routes.
CURRENCY_SERVER_PACKAGE = "@medusajs/medusa"

CURRENCY_SERVER_VERSION = "2.21.1"

#: Upstream server pagination defaults, pinned by the core currency query
#: config (``defaultStoreCurrencyFields`` / ``listTransformQueryConfig``).
CURRENCY_LIST_DEFAULT_LIMIT = 50

CURRENCY_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model projects a bounded page, so one page is
#: capped at this many currencies.
CURRENCY_LIST_MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class CurrencyRoute:
	"""One pinned Medusa Store Currency route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the
	route; both currency routes pin one.
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


CURRENCY_ROUTES: tuple[CurrencyRoute, ...] = (
	CurrencyRoute(
		method="GET",
		path="/store/currencies",
		request_type=None,
		response_type="StoreCurrencyListResponse",
		auth="publishable-key",
		sdk_method=None,
		query_type="StoreGetCurrencyListParams",
	),
	CurrencyRoute(
		method="GET",
		path="/store/currencies/{code}",
		request_type=None,
		response_type="StoreCurrencyResponse",
		auth="publishable-key",
		sdk_method=None,
		query_type="StoreGetCurrencyParams",
	),
)
