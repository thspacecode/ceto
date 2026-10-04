"""Pinned contract manifest for the Medusa Store Customer routes.

Source of truth: <https://docs.medusajs.com/api/store/customers>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 0 pins the contract only — no customer handlers are implemented here and
no route is registered on the router. The manifest is pure Python (no Frappe
imports) so it can drive request validation codegen and be tested standalone.

Request/response/query type names follow the official ``HttpTypes`` published
in ``@medusajs/types@2.21.1`` (the lockstep release used to verify the SDK
contract, ``@medusajs/js-sdk@2.21.1``): ``http/customer/store`` for the
domain types and ``http/common`` for the shared ``SelectParams`` fields
selector. Every route below is covered by a dedicated SDK method on
``sdk.store.customer`` (verified against the published SDK sources), so —
unlike the carts manifest — no route needs a raw HTTP client.

Authentication follows the SDK route docs: every Store route requires the
publishable key; ``POST /store/customers`` requires the single-purpose
``registration`` bearer token issued by the register auth route (Ceto creates
neither User nor Customer there — see ``ceto/services/auth/tokens.py``);
every ``/me`` route requires an authenticated customer (session or bearer).
"""

from dataclasses import dataclass

CUSTOMER_API_SOURCE_URL = "https://docs.medusajs.com/api/store/customers"

CUSTOMER_SDK_PACKAGE = "@medusajs/js-sdk"

CUSTOMER_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
CUSTOMER_TYPES_PACKAGE = "@medusajs/types"

CUSTOMER_TYPES_VERSION = "2.21.1"

#: Customer methods directly exposed by the pinned SDK version. Every pinned
#: route has a matching method, so no customer route requires a raw client.
CUSTOMER_SDK_METHODS = (
	"create",
	"retrieve",
	"update",
	"listAddress",
	"createAddress",
	"retrieveAddress",
	"updateAddress",
	"deleteAddress",
)


@dataclass(frozen=True, slots=True)
class CustomerRoute:
	"""One pinned Medusa Store Customer route contract.

	``query_type`` names the pinned ``HttpTypes`` query contract of the route
	(``None`` when the route accepts no query parameters — the delete route).
	``SelectParams`` is the domain-neutral shared fields selector of
	``http/common`` in the pinned ``@medusajs/types`` release.
	"""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None
	query_type: str | None = None


CUSTOMER_ROUTES: tuple[CustomerRoute, ...] = (
	# Registration completes through the customers API: the register auth
	# route only issues the single-purpose registration token, so the create
	# call is the first route that mints the customer identity.
	CustomerRoute(
		method="POST",
		path="/store/customers",
		request_type="StoreCreateCustomer",
		response_type="StoreCustomerResponse",
		auth="publishable-key+registration-token",
		sdk_method="create",
		query_type="SelectParams",
	),
	CustomerRoute(
		method="GET",
		path="/store/customers/me",
		request_type=None,
		response_type="StoreCustomerResponse",
		auth="publishable-key+customer-session",
		sdk_method="retrieve",
		query_type="StoreGetCustomerParams",
	),
	# The pinned update payload (StoreUpdateCustomer) deliberately omits
	# email: the profile update route cannot change the login identity.
	CustomerRoute(
		method="POST",
		path="/store/customers/me",
		request_type="StoreUpdateCustomer",
		response_type="StoreCustomerResponse",
		auth="publishable-key+customer-session",
		sdk_method="update",
		query_type="SelectParams",
	),
	CustomerRoute(
		method="GET",
		path="/store/customers/me/addresses",
		request_type=None,
		response_type="StoreCustomerAddressListResponse",
		auth="publishable-key+customer-session",
		sdk_method="listAddress",
		query_type="StoreCustomerAddressFilters",
	),
	CustomerRoute(
		method="POST",
		path="/store/customers/me/addresses",
		request_type="StoreCreateCustomerAddress",
		response_type="StoreCustomerResponse",
		auth="publishable-key+customer-session",
		sdk_method="createAddress",
		query_type="SelectParams",
	),
	CustomerRoute(
		method="GET",
		path="/store/customers/me/addresses/{address_id}",
		request_type=None,
		response_type="StoreCustomerAddressResponse",
		auth="publishable-key+customer-session",
		sdk_method="retrieveAddress",
		query_type="StoreGetCustomerAddressParams",
	),
	CustomerRoute(
		method="POST",
		path="/store/customers/me/addresses/{address_id}",
		request_type="StoreUpdateCustomerAddress",
		response_type="StoreCustomerResponse",
		auth="publishable-key+customer-session",
		sdk_method="updateAddress",
		query_type="SelectParams",
	),
	CustomerRoute(
		method="DELETE",
		path="/store/customers/me/addresses/{address_id}",
		request_type=None,
		response_type="StoreCustomerAddressDeleteResponse",
		auth="publishable-key+customer-session",
		sdk_method="deleteAddress",
		query_type=None,
	),
)
