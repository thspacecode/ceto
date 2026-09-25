"""Pinned contract manifest for the Medusa Store Cart routes.

Source of truth: <https://docs.medusajs.com/api/store/carts>.
Compatibility layer: ``@medusajs/js-sdk@2.21.1``.

Phase 0 pins the contract only — no cart handlers are implemented here. The
manifest is pure Python (no Frappe imports) so it can drive request validation
codegen and be tested standalone.

Request/response type names follow the official ``HttpTypes`` published in
``@medusajs/types@2.21.1`` (the lockstep release used to verify the SDK contract). Two routes currently documented by Medusa have **no** official payload
type in that package (``gift-cards`` and ``store-credits``); their
``request_type`` values below are Ceto placeholders, marked with comments.
"""

from dataclasses import dataclass

CART_API_SOURCE_URL = "https://docs.medusajs.com/api/store/carts"

CART_SDK_PACKAGE = "@medusajs/js-sdk"

CART_SDK_VERSION = "2.21.1"

#: Lockstep ``@medusajs/types`` release used to verify the SDK contract. This
#: package publishes the ``HttpTypes`` names used below.
CART_TYPES_PACKAGE = "@medusajs/types"

CART_TYPES_VERSION = "2.21.1"

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
	# No official HttpTypes payload for gift-cards in @medusajs/types@2.21.1;
	# "StoreAddCartGiftCards" is a Ceto placeholder name.
	CartRoute(
		method="POST",
		path="/store/carts/{id}/gift-cards",
		request_type="StoreAddCartGiftCards",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# No official HttpTypes payload for gift-cards in @medusajs/types@2.21.1;
	# the removal route carries an empty body.
	CartRoute(
		method="DELETE",
		path="/store/carts/{id}/gift-cards",
		request_type=None,
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
		sdk_method=None,
	),
	# No official HttpTypes payload for store-credits in @medusajs/types@2.21.1;
	# "StoreAddCartStoreCredits" is a Ceto placeholder name.
	CartRoute(
		method="POST",
		path="/store/carts/{id}/store-credits",
		request_type="StoreAddCartStoreCredits",
		response_type="StoreCartResponse",
		auth="publishable-key+optional-session",
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
