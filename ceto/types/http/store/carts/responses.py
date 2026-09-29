from pydantic import BaseModel

from ceto.types.http.store.carts.entities import StoreCart


class StoreCartResponse(BaseModel):
	cart: StoreCart
