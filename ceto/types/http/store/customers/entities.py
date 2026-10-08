"""Pinned Medusa Store Customer entities (Phase 0 contract).

Mirrors ``StoreCustomer`` / ``StoreCustomerAddress`` of the pinned
``HttpTypes`` of ``@medusajs/types@2.21.1`` (``http/customer/store``) for the
columns Ceto can derive from ERPNext (see ``docs/customers/field-mapping.md``).
Columns the pinned type marks non-nullable (``customer_id``, the default
flags, the address timestamps) are required; nullable columns default to
``None`` like every Ceto entity so serializers may omit unset columns.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StoreCustomerAddress(BaseModel):
	"""Medusa ``StoreCustomerAddress`` entity (Phase 0 baseline).

	Mirrors the pinned ``BaseCustomerAddress`` columns of
	``@medusajs/types@2.21.1``: unlike the cart-scoped
	``StoreCartAddress`` the address book entry always names its owning
	customer and always carries the default flags and timestamps.
	"""

	id: str
	customer_id: str
	is_default_shipping: bool
	is_default_billing: bool
	address_name: str | None = None
	company: str | None = None
	first_name: str | None = None
	last_name: str | None = None
	phone: str | None = None
	address_1: str | None = None
	address_2: str | None = None
	city: str | None = None
	province: str | None = None
	postal_code: str | None = None
	country_code: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime
	updated_at: datetime


class StoreCustomer(BaseModel):
	"""Medusa ``StoreCustomer`` entity (Phase 0 baseline).

	Mirrors the pinned ``StoreCustomer`` of ``@medusajs/types@2.21.1``: the
	pinned type itself drops ``created_by`` from ``BaseCustomer`` and so does
	this model. ``deleted_at`` is omitted as Ceto policy — Ceto exposes no
	soft-deleted customer surface in Phase 0 (see
	``docs/customers/field-mapping.md``).
	"""

	id: str
	email: str
	default_billing_address_id: str | None = None
	default_shipping_address_id: str | None = None
	company_name: str | None = None
	first_name: str | None = None
	last_name: str | None = None
	phone: str | None = None
	metadata: dict[str, Any] | None = None
	addresses: list[StoreCustomerAddress] = Field(default_factory=list)
	created_at: datetime | None = None
	updated_at: datetime | None = None
