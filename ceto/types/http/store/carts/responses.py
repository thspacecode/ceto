from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.carts.entities import StoreCart
from ceto.types.http.store.orders import StoreOrder


class StoreCartResponse(BaseModel):
	cart: StoreCart


class StoreLineItemDeleteResponse(BaseModel):
	model_config = ConfigDict(extra="forbid")

	id: str
	object: Literal["line-item"] = "line-item"
	deleted: Literal[True] = True
	parent: str


class StoreCompleteCartError(BaseModel):
	"""The pinned ``error`` object of a completion that returned the cart.

	Mirrors the failure member of ``StoreCompleteCartResponse`` of the
	pinned ``HttpTypes`` of ``@medusajs/types@2.21.1``: the message, name
	and type of the error that kept the cart open.
	"""

	message: str
	name: str
	type: str


class StoreCompleteCartSuccess(BaseModel):
	"""The ``type: "order"`` union member: the cart was completed."""

	type: Literal["order"] = "order"
	order: StoreOrder


class StoreCompleteCartFailure(BaseModel):
	"""The ``type: "cart"`` union member: the cart was not completed."""

	type: Literal["cart"] = "cart"
	cart: StoreCart
	error: StoreCompleteCartError


#: Pinned ``StoreCompleteCartResponse`` of ``@medusajs/types@2.21.1``: a
#: discriminated union on ``type`` — the placed order on success, the cart
#: plus a structured error otherwise.
StoreCompleteCartResponse = Annotated[
	StoreCompleteCartSuccess | StoreCompleteCartFailure,
	Field(discriminator="type"),
]
