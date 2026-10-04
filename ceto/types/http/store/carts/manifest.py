"""Pinned contract manifest for the Medusa Store Cart routes.

Source of truth: <https://docs.medusajs.com/api/store/carts>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 0 pins the contract only — no cart handlers are implemented here. The
manifest is pure Python (no Frappe imports) so it can drive request validation
codegen and be tested standalone.

Request/response type names follow the official ``HttpTypes`` published in
``@medusajs/types@2.21.1`` (the lockstep release used to verify the SDK contract). The three loyalty routes (``gift-cards`` add/remove and
``store-credits``) have **no** official payload type in that package: they
belong to the loyalty plugin Medusa documents alongside the core Store API,
so their ``request_type`` values are pinned to
``@zjedene-medusa/loyalty-plugin`` (see ``CART_LOYALTY_PLUGIN_VERSION``).
The plugin middleware also requires an authenticated customer for
``store-credits``, while the gift-card routes stay on the optional cart
session.
"""

from dataclasses import dataclass

CART_API_SOURCE_URL = "https://docs.medusajs.com/api/store/carts"

CART_SDK_PACKAGE = "@medusajs/js-sdk"

CART_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
CART_TYPES_PACKAGE = "@medusajs/types"

CART_TYPES_VERSION = "2.21.1"

#: The gift-card and store-credit cart routes are not part of the Medusa core
#: Store API; the loyalty plugin owns them and Medusa documents them next to
#: the core routes. Its release pins the payload names, shapes and middleware
#: (customer authentication for store-credits) used below.
CART_LOYALTY_PLUGIN_PACKAGE = "@zjedene-medusa/loyalty-plugin"

CART_LOYALTY_PLUGIN_VERSION = "2.16.2"

#: Cart methods directly exposed by the pinned SDK version. Routes without a
#: matching method (taxes, gift cards, store credits) require a raw HTTP client.
CART_SDK_METHODS = (
	"create",
	"retrieve",
	"update",
	"createLineItem",
	"updateLineItem",
	"deleteLineItem",
	"addShippingMethod",
	"addPromotions",
	"removePromotions",
	"complete",
	"transferCart",
)


@dataclass(frozen=True, slots=True)
class CartRoute:
	"""One pinned Medusa Store Cart route contract."""

	method: str
	path: str
	request_type: str | None
	response_type: str
	auth: str
	sdk_method: str | None


CART_ROUTES: tuple[CartRoute, ...] = (
	CartRoute(
		method="GET",
		path="/store/carts/{id}",
		request_type=None,
		response_type="StoreCartResponse",
		auth="publishable-key",
		sdk_method="retrieve",
	),
	CartRoute(
		method="POST",
		path="/store/carts",
		request_type="StoreCreateCart",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="create",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}",
		request_type="StoreUpdateCart",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="update",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/line-items",
		request_type="StoreAddCartLineItem",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="createLineItem",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/line-items/{line_id}",
		request_type="StoreUpdateCartLineItem",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="updateLineItem",
	),
	CartRoute(
		method="DELETE",
		path="/store/carts/{id}/line-items/{line_id}",
		request_type=None,
		response_type="StoreLineItemDeleteResponse",
		auth="publishable-key+optional-session",
		sdk_method="deleteLineItem",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/shipping-methods",
		request_type="StoreAddCartShippingMethods",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="addShippingMethod",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/promotions",
		request_type="StoreCartAddPromotion",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="addPromotions",
	),
	CartRoute(
		method="DELETE",
		path="/store/carts/{id}/promotions",
		request_type="StoreCartRemovePromotion",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="removePromotions",
	),
	# Pinned to the loyalty plugin validators (@zjedene-medusa/
	# loyalty-plugin@2.16.2): StoreAddGiftCardToCart is {code} in a strict
	# object; the route keeps the optional cart session.
	CartRoute(
		method="POST",
		path="/store/carts/{id}/gift-cards",
		request_type="StoreAddGiftCardToCart",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# The pinned removal route is bodyful: StoreRemoveGiftCardFromCart carries
	# {code} on the DELETE, in a strict object.
	CartRoute(
		method="DELETE",
		path="/store/carts/{id}/gift-cards",
		request_type="StoreRemoveGiftCardFromCart",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# StoreAddStoreCreditsToCart carries an optional positive {amount}; the
	# plugin middleware authenticates the customer (session or bearer), so the
	# route requires a customer session.
	CartRoute(
		method="POST",
		path="/store/carts/{id}/store-credits",
		request_type="StoreAddStoreCreditsToCart",
		response_type="StoreCartResponse",
		auth="publishable-key+customer-session",
		sdk_method=None,
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/taxes",
		request_type="StoreCalculateCartTaxes",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# Transfer requires an authenticated customer JWT. The official payload
	# type StoreUpdateCartCustomer is an empty interface in 2.21.1 and the SDK
	# sends no body, so request_type is None.
	CartRoute(
		method="POST",
		path="/store/carts/{id}/customer",
		request_type=None,
		response_type="StoreCartResponse",
		auth="publishable-key+customer-session",
		sdk_method="transferCart",
	),
	CartRoute(
		method="POST",
		path="/store/carts/{id}/complete",
		request_type="StoreCompleteCart",
		response_type="StoreCompleteCartResponse",
		auth="publishable-key+optional-session",
		sdk_method="complete",
	),
)
