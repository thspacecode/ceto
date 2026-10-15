"""Pinned contract manifest for the Medusa Store payment routes.

Source of truth: <https://docs.medusajs.com/api/store/payment-collections>
and <https://docs.medusajs.com/api/store/payment-providers>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 5 slices 5A/5B pin the contract and build the Ceto-side persistence
and provider registry (``ceto.services.payments``); no payment route is
served yet. The manifest is pure Python (no Frappe imports) so it can drive
request validation codegen and be tested standalone.

Request/response type names follow the official ``HttpTypes`` published in
``@medusajs/types@2.21.1`` (the lockstep release used to verify the SDK
contract). The pinned store payment surface is deliberately tiny: Medusa
v2 checkout creates the cart's payment collection and one session on it,
then completes the cart — session updates, deletion and authorization are
admin/module flows, not store routes, in the pinned release (verified
against the lockstep server implementation, ``@medusajs/medusa@2.21.1``).

Authentication is verified against the same lockstep server: the framework
enforces the publishable API key for the whole ``/store`` namespace and the
three payment routes add **no** customer-authentication middleware — guest
checkouts create collections and sessions, while the session workflow picks
up the authenticated customer's actor id when a session exists (hence the
``publishable-key+optional-session`` labels, matching the cart routes).

The SDK exposes exactly two store payment methods. ``initiatePaymentSession``
creates the cart's missing payment collection inline (``POST
/store/payment-collections``) before initializing the session, so the
collection-create route has no dedicated SDK method of its own.
"""

from dataclasses import dataclass

PAYMENT_API_SOURCE_URL = "https://docs.medusajs.com/api/store/payment-collections"

PAYMENT_PROVIDERS_SOURCE_URL = "https://docs.medusajs.com/api/store/payment-providers"

PAYMENT_SDK_PACKAGE = "@medusajs/js-sdk"

PAYMENT_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
PAYMENT_TYPES_PACKAGE = "@medusajs/types"

PAYMENT_TYPES_VERSION = "2.21.1"

#: Lockstep server implementation used to verify the facts the SDK/types
#: packages do not carry: the route set (no store session update/delete/
#: authorize routes), the per-route middlewares (no customer authentication)
#: and the validators (strict bodies, required ``region_id`` filter, list
#: pagination defaults).
PAYMENT_SERVER_PACKAGE = "@medusajs/medusa"

PAYMENT_SERVER_VERSION = "2.21.1"

#: Payment methods directly exposed by the pinned SDK version.
PAYMENT_SDK_METHODS = (
	"listPaymentProviders",
	"initiatePaymentSession",
)

#: Upstream server pagination defaults, pinned by the core
#: ``StoreGetPaymentProvidersParams`` validator (``createFindParams({limit:
#: 20, offset: 0})`` merged with the required ``region_id``).
PAYMENT_PROVIDER_LIST_DEFAULT_LIMIT = 20

PAYMENT_PROVIDER_LIST_DEFAULT_OFFSET = 0


@dataclass(frozen=True, slots=True)
class PaymentRoute:
	"""One pinned Medusa Store payment route contract."""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None


PAYMENT_ROUTES: tuple[PaymentRoute, ...] = (
	# Body {cart_id} (strict object). Idempotent-ish upstream: an existing
	# collection for the cart is returned as-is instead of a second one being
	# created. The SDK calls this route inline from initiatePaymentSession,
	# so no dedicated SDK method exists.
	PaymentRoute(
		method="POST",
		path="/store/payment-collections",
		request_type="StoreCreatePaymentCollection",
		response_type="StorePaymentCollectionResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# Body {provider_id, data?} (strict object). The HttpTypes payload name
	# is StoreInitializePaymentSession; the pinned core validator pins the
	# same shape under the alias StoreCreatePaymentSession. Creates the
	# session on the collection and returns the whole collection.
	PaymentRoute(
		method="POST",
		path="/store/payment-collections/{id}/payment-sessions",
		request_type="StoreInitializePaymentSession",
		response_type="StorePaymentCollectionResponse",
		auth="publishable-key+optional-session",
		sdk_method="initiatePaymentSession",
	),
	# Query-only (no request body); region_id is required — the route is
	# pinned to refuse the request without it. Response is the pinned
	# PaginatedResponse envelope: {payment_providers, count, offset, limit}.
	PaymentRoute(
		method="GET",
		path="/store/payment-providers",
		request_type=None,
		response_type="StorePaymentProviderListResponse",
		auth="publishable-key",
		sdk_method="listPaymentProviders",
	),
)
