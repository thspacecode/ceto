from typing import Literal

from pydantic import BaseModel, ConfigDict

from ceto.types.http.store.carts.entities import StoreCart


class StoreCartResponse(BaseModel):
	cart: StoreCart


class StoreLineItemDeleteResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	object: Literal["line-item"] = "line-item"
	deleted: Literal[True] = True
	parent: str
