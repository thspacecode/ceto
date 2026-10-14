"""Thin Medusa Store shipping-option endpoints (Phase 4 slice 2)."""

from typing import Any

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.shipping.service import ShippingOptionsService
from ceto.types.http.store.shipping_options import (
	StoreCalculateShippingOptionPrice,
	StoreGetShippingOptionList,
	StoreShippingOptionListResponse,
	StoreShippingOptionResponse,
)


@ceto_router.get("/store/shipping-options", allow_guest=True)
def list_shipping_options(**query: Any) -> StoreShippingOptionListResponse:
	"""Medusa ``listCartOptions``: the shipping options of one open cart.

	Guest-dispatchable like upstream pins it — no customer session exists
	and the publishable key is the only credential, required exactly as on
	every Store route, with the cart key's region / sales-channel scope
	enforced against the resolved cart through the shared ``guard`` seam
	(the cart surface refuses a wrong-scoped key with ``403 not_allowed``).
	The pinned ``StoreGetShippingOptionList`` validates the query before
	anything resolves: ``cart_id`` is the required scope, ``is_return=true``
	serves the empty option set (ERPNext ``Selling`` rules have no
	return-rate source), and every other key — the dead ``FindParams``
	pagination the pinned route ignores, the ``fields`` selector, the
	``order`` sort, the ``$and``/``$or`` combinators — fails as ``400
	invalid_data``. An unknown, claimed-elsewhere or non-open cart is the
	masked ``404 not_found`` of the whole cart surface.
	"""
	publishable_key = CartPublishableKey.from_request()
	filters = StoreGetShippingOptionList.model_validate(query)
	return ShippingOptionsService().list(
		filters.cart_id, is_return=filters.is_return, guard=publishable_key.check_reference
	)


@ceto_router.post("/store/shipping-options/{id}/calculate", allow_guest=True)
def calculate_shipping_option_price(id: str, **payload: Any) -> StoreShippingOptionResponse:
	"""Medusa ``calculate``: one option's calculated price on one open cart.

	Guest-dispatchable with the publishable key required and scoped exactly
	like the list. The pinned ``StoreCalculateShippingOptionPrice`` body is
	validated strictly: the ``cart_id`` scope is required and unknown keys
	fail as ``400 invalid_data`` — including any query parameter, because
	the router merges query parameters into the same argument mapping and
	the pinned calculate query accepts nothing
	(:class:`~ceto.types.http.store.shipping_options.StoreShippingOptionCalculateParams`).
	The optional provider ``data`` is accepted for request compatibility
	only and never persisted: the ERPNext compatibility field for a shipping
	option is the ``Shipping Rule`` master, which carries no provider
	payload. An unknown, ineligible or malformed option id and a masked cart
	are all the same ``404 not_found`` from the service.
	"""
	publishable_key = CartPublishableKey.from_request()
	validated = StoreCalculateShippingOptionPrice.model_validate(payload)
	return ShippingOptionsService().calculate(validated.cart_id, id, guard=publishable_key.check_reference)
