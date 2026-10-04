"""Pinned Medusa Store Customer response bodies (Phase 0 contract).

Mirrors the pinned ``StoreCustomerResponse``, ``StoreCustomerAddressResponse``,
``StoreCustomerAddressListResponse`` and ``StoreCustomerAddressDeleteResponse``
of the ``HttpTypes`` of ``@medusajs/types@2.21.1`` (``http/customer/store``).

The pinned ``StoreCustomerAddressDeleteResponse`` is a
``DeleteResponseWithParent<"address", StoreCustomer>``: the parent is the full
customer object (the SDK destructures ``{ deleted, parent: customer }``), not
an id like the carts line-item delete.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from ceto.types.http.store.customers.entities import StoreCustomer, StoreCustomerAddress


class StoreCustomerResponse(BaseModel):
	"""Body of every customer create/retrieve/update route."""

	customer: StoreCustomer


class StoreCustomerAddressResponse(BaseModel):
	"""Body of ``GET /store/customers/me/addresses/{address_id}``."""

	address: StoreCustomerAddress


class StoreCustomerAddressListResponse(BaseModel):
	"""Body of ``GET /store/customers/me/addresses``.

	Mirrors the pinned ``PaginatedResponse`` of ``@medusajs/types@2.21.1``
	minus ``estimate_count``: the planner estimate is a Postgres-specific
	feature flag with no ERPNext equivalent, so Ceto never reports it
	(recorded decision in ``docs/customers/field-mapping.md``).
	"""

	addresses: list[StoreCustomerAddress]
	count: int
	offset: int
	limit: int


class StoreCustomerAddressDeleteResponse(BaseModel):
	"""Body of ``DELETE /store/customers/me/addresses/{address_id}``.

	Pins the exact deletion shape (unknown fields rejected): the removed
	address id, the ``address`` object literal, the ``deleted`` flag and the
	unchanged parent customer.
	"""

	model_config = ConfigDict(extra="forbid")

	id: str
	object: Literal["address"] = "address"
	deleted: Literal[True] = True
	parent: StoreCustomer
