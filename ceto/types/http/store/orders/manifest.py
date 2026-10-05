"""Pinned contract manifest for the Medusa Store Order routes.

Source of truth: <https://docs.medusajs.com/api/store/orders>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 0 pinned the contract only — the manifest itself stays contract-only
and carries no handlers: Phase 2 implements the retrieve route and Phase 3
the list route, both in ``ceto/api/store/orders.py``, while the four
transfer routes remain contract-only until their phase registers them
(``ceto.tests.types.http.store.test_orders_manifest`` enforces the
boundary). The manifest is pure Python (no Frappe imports) so it can drive
request validation codegen and be tested standalone.

Request/response type names follow the official ``HttpTypes`` published in
``@medusajs/types@2.21.1`` (the lockstep release used to verify the SDK
contract). Unlike the cart surface, **every** pinned order route has a direct
SDK method — the orders surface needs no raw-HTTP escape hatch.

Authentication is verified against the lockstep server implementation
(``@medusajs/medusa@2.21.1``): the framework enforces the publishable API key
for the whole ``/store`` namespace; ``GET /store/orders`` and the transfer
``request``/``cancel`` routes add required customer authentication (session or
bearer); ``GET /store/orders/{id}`` is intentionally unauthenticated — the
unguessable order id is the capability, per the core route's own comment; the
transfer ``accept``/``decline`` routes authorize with the single-use transfer
token in the body and carry no customer authentication middleware.

Transfer tokens are created by ``request`` as a UUID v4 stored on the pending
transfer order-change, emitted through the ``order.transfer_requested`` event
and delivered to the order's email as a notification (the pinned ``token``
payload field is documented as "The transfer token received in the email
notification"). The pinned packages define **no** token expiry: upstream, the
token is valid while its request is pending and dies when the request is
accepted, declined or cancelled — replay of a consumed token fails.

The request route's pinned payload carries **no recipient identifier**: the
authenticated customer requests ownership for themselves, the pending
transfer records that requesting customer, and acceptance applies ownership
to it — upstream ships no owner-nominates-recipient route, superseding the
preliminary PRD assumption (see ``docs/orders/field-mapping.md``).

Ceto deliberately hardens beyond that contract (Ceto decisions, recorded in
``docs/orders/field-mapping.md`` — **not** upstream parity): the plaintext
token is never persisted — only its digest — and a pending transfer expires
``ORDER_TRANSFER_LIFETIME_DAYS`` after its request was created, expired
tokens failing with the same safe ``not_allowed`` family as a wrong token, so
expiry leaks nothing and changes no ownership.
"""

from dataclasses import dataclass

ORDER_API_SOURCE_URL = "https://docs.medusajs.com/api/store/orders"

ORDER_SDK_PACKAGE = "@medusajs/js-sdk"

ORDER_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
ORDER_TYPES_PACKAGE = "@medusajs/types"

ORDER_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the ``/store`` publishable-key middleware, the
#: per-route customer-authentication middlewares, the list validator
#: defaults/filters and the transfer workflows (token, event, terminal states).
ORDER_SERVER_PACKAGE = "@medusajs/medusa"

ORDER_SERVER_VERSION = "2.21.1"

#: Order methods directly exposed by the pinned SDK version — the SDK covers
#: the whole orders surface.
ORDER_SDK_METHODS = (
	"list",
	"retrieve",
	"requestTransfer",
	"cancelTransfer",
	"acceptTransfer",
	"declineTransfer",
)

#: Pinned ``StoreOrderFilters`` fields of ``@medusajs/types@2.21.1`` (each a
#: string or a string list). The upstream list validator additionally accepts
#: ``$and``/``$or`` combinators; Ceto pins the plain fields only (see
#: ``docs/orders/field-mapping.md``).
ORDER_LIST_FILTERS = ("id", "status")

#: Upstream server pagination defaults, pinned by the core ``StoreGetOrdersParams``
#: validator (``createFindParams({offset: 0, limit: 50})``).
ORDER_LIST_DEFAULT_LIMIT = 50

ORDER_LIST_DEFAULT_OFFSET = 0

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 validator bounds no
#: page size): the list read model loads a page's whole context at once, so one
#: page is capped at this many orders instead of loading a whole ledger. The
#: query contract rejects a larger (or negative) page as ``400 invalid_data``.
ORDER_LIST_MAX_LIMIT = 100

#: Ceto decision (NOT upstream parity — the pinned 2.21.1 packages define no
#: transfer expiry): a pending order transfer expires this many days after
#: its request was created. Expired tokens fail with the same safe
#: ``not_allowed`` error family as a wrong token — no distinguishable expiry
#: error exists, so expiry leaks nothing and changes no ownership.
ORDER_TRANSFER_LIFETIME_DAYS = 7


@dataclass(frozen=True, slots=True)
class OrderRoute:
	"""One pinned Medusa Store Order route contract."""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None


ORDER_ROUTES: tuple[OrderRoute, ...] = (
	# Intentionally unauthenticated upstream (the core route comment: the
	# unguessable order id is the authentication mechanism); the SDK inlines
	# the response as {order: StoreOrder} — the pinned StoreOrderResponse name.
	OrderRoute(
		method="GET",
		path="/store/orders/{id}",
		request_type=None,
		response_type="StoreOrderResponse",
		auth="publishable-key",
		sdk_method="retrieve",
	),
	# Requires an authenticated customer; the server forces the customer_id
	# filter to the authenticated actor (and excludes draft orders). The
	# response is the pinned PaginatedResponse envelope:
	# {orders, count, offset, limit}. Upstream pins no default sort order.
	OrderRoute(
		method="GET",
		path="/store/orders",
		request_type=None,
		response_type="StoreOrderListResponse",
		auth="publishable-key+customer-session",
		sdk_method="list",
	),
	# Body {description?, update_order_email?} — **no recipient identifier**.
	# Requires an authenticated customer; guest customers, cancelled orders
	# and orders the customer already owns are rejected. The authenticated
	# customer requests ownership for themselves: the pending transfer
	# records that requesting customer and acceptance applies ownership to
	# it (verified in @medusajs/order 2.21.1 transfer-customer.js; upstream
	# ships no owner-nominates-recipient route, superseding the preliminary
	# PRD assumption — see docs/orders/field-mapping.md). Creates the
	# pending transfer (a UUID v4 token, persisted by Ceto as a digest only,
	# never plaintext) and emits order.transfer_requested — the token
	# reaches the order's email as a notification, never the API response.
	OrderRoute(
		method="POST",
		path="/store/orders/{id}/transfer/request",
		request_type="StoreRequestOrderTransfer",
		response_type="StoreOrderResponse",
		auth="publishable-key+customer-session",
		sdk_method="requestTransfer",
	),
	# Body {token} (required). No customer authentication: the single-use
	# transfer token authorizes. Confirms the pending transfer — ownership
	# moves to the requesting customer (optionally updating the order email).
	# A wrong token is not_allowed; a missing pending request is invalid_data.
	OrderRoute(
		method="POST",
		path="/store/orders/{id}/transfer/accept",
		request_type="StoreAcceptOrderTransfer",
		response_type="StoreOrderResponse",
		auth="publishable-key+transfer-token",
		sdk_method="acceptTransfer",
	),
	# No request body: the SDK sends none and the pinned server middleware
	# validates no body. Requires an authenticated customer; only the
	# customer who requested the transfer may cancel it. Deletes the pending
	# transfer request, killing its token.
	OrderRoute(
		method="POST",
		path="/store/orders/{id}/transfer/cancel",
		request_type=None,
		response_type="StoreOrderResponse",
		auth="publishable-key+customer-session",
		sdk_method="cancelTransfer",
	),
	# Body {token} (required), like accept — token-authorized, no customer
	# authentication. The HttpTypes name is StoreDeclineOrderTransfer; the
	# pinned core validator carries the same shape under the alias
	# StoreDeclineOrderTransferRequest. Marks the pending transfer declined
	# (terminal); a wrong token is not_allowed.
	OrderRoute(
		method="POST",
		path="/store/orders/{id}/transfer/decline",
		request_type="StoreDeclineOrderTransfer",
		response_type="StoreOrderResponse",
		auth="publishable-key+transfer-token",
		sdk_method="declineTransfer",
	),
)
