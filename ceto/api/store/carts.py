from typing import Any

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.types.http.store.carts import StoreCreateCart, StoreUpdateCart


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
	reference, _ = CartService().retrieve(id)
	publishable_key.check_reference(reference)
	reference, quotation = CartService().update(id, validated)
	publishable_key.check_reference(reference)
	return {"cart": CartSerializer().serialize(reference, quotation, fields=fields)}
