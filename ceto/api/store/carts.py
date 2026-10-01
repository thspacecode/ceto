from typing import Any

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCalculateCartTaxes,
	StoreCartAddPromotion,
	StoreCartRemovePromotion,
	StoreCreateCart,
	StoreUpdateCart,
	StoreUpdateCartLineItem,
)


@ceto_router.get("/store/carts/{id}", allow_guest=True)
def retrieve_cart(id: str, fields: str | None = None) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	reference, quotation = CartService().retrieve(id)
	publishable_key.check_reference(reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts", allow_guest=True)
def create_cart(fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = publishable_key.apply_create_defaults(StoreCreateCart.model_validate(payload))
	reference, quotation = CartService().create(validated)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}", allow_guest=True)
def update_cart(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreUpdateCart.model_validate(payload)
	publishable_key.check_update(validated)
	# The scope check runs inside the cart row lock (before any mutation) so a
	# wrong-scoped key can never modify the cart and cannot be raced between
	# check and save.
	reference, quotation = CartService().update(id, validated, guard=publishable_key.check_reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}/line-items", allow_guest=True)
def add_cart_line_item(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreAddCartLineItem.model_validate(payload)
	# guard validates the key scope against the locked reference before the
	# Quotation is mutated (see update_cart).
	reference, quotation, _mapping = CartService().add_line_item(
		id, validated, guard=publishable_key.check_reference
	)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}/line-items/{line_id}", allow_guest=True)
def update_cart_line_item(id: str, line_id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreUpdateCartLineItem.model_validate(payload)
	reference, quotation, _mapping = CartService().update_line_item(
		id, line_id, validated, guard=publishable_key.check_reference
	)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.delete("/store/carts/{id}/line-items/{line_id}", allow_guest=True)
def delete_cart_line_item(id: str, line_id: str) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	reference, _quotation, mapping = CartService().delete_line_item(
		id, line_id, guard=publishable_key.check_reference
	)
	# Medusa delete-line shape: no cart wrapper, exactly these keys.
	return {
		"id": mapping.line_id,
		"object": "line-item",
		"deleted": True,
		"parent": reference.cart_id,
	}


@ceto_router.post("/store/carts/{id}/shipping-methods", allow_guest=True)
def add_cart_shipping_method(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreAddCartShippingMethods.model_validate(payload)
	# guard validates the key scope against the locked reference before the
	# Quotation is mutated (see update_cart). The optional provider `data` of
	# the payload is accepted but never persisted: the ERPNext compatibility
	# field for a shipping method is the Shipping Rule link, which carries no
	# provider payload.
	reference, quotation = CartService().set_shipping_method(
		id, validated, guard=publishable_key.check_reference
	)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}/promotions", allow_guest=True)
def add_cart_promotions(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreCartAddPromotion.model_validate(payload)
	# guard validates the key scope against the locked reference before the
	# Quotation is mutated (see update_cart).
	reference, quotation = CartService().add_promotions(id, validated, guard=publishable_key.check_reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.delete("/store/carts/{id}/promotions", allow_guest=True)
def delete_cart_promotions(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	validated = StoreCartRemovePromotion.model_validate(payload)
	# guard validates the key scope against the locked reference before the
	# Quotation is mutated (see update_cart).
	reference, quotation = CartService().remove_promotions(
		id, validated, guard=publishable_key.check_reference
	)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}/taxes", allow_guest=True)
def calculate_cart_taxes(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	publishable_key = CartPublishableKey.from_request()
	# The pinned StoreCalculateCartTaxes body is empty: validation exists to
	# reject unexpected fields, not to carry options.
	StoreCalculateCartTaxes.model_validate(payload)
	# guard validates the key scope against the locked reference before the
	# Quotation is recalculated (see update_cart).
	reference, quotation = CartService().calculate_taxes(id, guard=publishable_key.check_reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}


@ceto_router.post("/store/carts/{id}/customer", allow_guest=True)
def claim_cart_customer(id: str, fields: str | None = None) -> dict[str, Any]:
	"""Medusa ``transferCart``: claim a guest cart for the logged-in customer.

	The route is guest-enabled like the other cart routes but always rejects
	an unauthenticated session with ``401 unauthorized``; the publishable-key
	scope is validated inside the cart row lock via ``guard``.
	"""
	publishable_key = CartPublishableKey.from_request()
	reference, quotation = CartClaim().claim(id, guard=publishable_key.check_reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}
