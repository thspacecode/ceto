"""Pinned Medusa Store Customer request payloads (Phase 0 contract).

Mirrors the pinned ``StoreCreateCustomer``, ``StoreUpdateCustomer``,
``StoreCreateCustomerAddress`` and ``StoreUpdateCustomerAddress`` of the
``HttpTypes`` of ``@medusajs/types@2.21.1`` (``http/customer/store``). Every
payload rejects unknown fields so new Medusa fields fail loudly instead of
being silently dropped.

``StoreUpdateCustomer`` mirrors the pinned ``Omit<BaseUpdateCustomer,
"email">``: the profile update cannot change the login identity, so ``email``
is not a field and an ``email`` key in the body is rejected (Ceto policy:
email changes go through the auth verification flow, see
``docs/customers/field-mapping.md``).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class StoreCreateCustomer(BaseModel):
	"""Body of ``POST /store/customers``.

	Mirrors the pinned ``StoreCreateCustomer`` of ``@medusajs/types@2.21.1``:
	every field is optional, including ``email`` — the caller is the
	registration token, whose subject already names the identity, so a body
	email that disagrees with it is rejected by the implementing route and
	an omitted one falls back to the token subject (Ceto policy, mirroring
	the emailpass credential update).
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	email: EmailStr | None = None
	company_name: str | None = None
	first_name: str | None = None
	last_name: str | None = None
	phone: str | None = None
	metadata: dict[str, Any] | None = None


class StoreUpdateCustomer(BaseModel):
	"""Body of ``POST /store/customers/me``.

	Mirrors the pinned ``StoreUpdateCustomer`` of ``@medusajs/types@2.21.1``
	(``Omit<BaseUpdateCustomer, "email">``): no ``email`` field exists and
	unknown fields — an ``email`` key included — are rejected.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	company_name: str | None = None
	first_name: str | None = None
	last_name: str | None = None
	phone: str | None = None
	metadata: dict[str, Any] | None = None


class _CustomerAddressPayload(BaseModel):
	"""Shared address-book body of the Medusa customer address routes.

	Mirrors the pinned ``BaseCreateCustomerAddress`` /
	``BaseUpdateCustomerAddress`` columns of ``@medusajs/types@2.21.1``,
	which are identical: every field is optional (Medusa merges the object
	into the stored address) including the default flags and the
	``address_name`` label the cart addresses do not carry.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	first_name: str | None = None
	last_name: str | None = None
	company: str | None = None
	phone: str | None = None
	address_1: str | None = None
	address_2: str | None = None
	city: str | None = None
	province: str | None = None
	postal_code: str | None = None
	country_code: str | None = None
	address_name: str | None = None
	is_default_shipping: bool | None = None
	is_default_billing: bool | None = None
	metadata: dict[str, Any] | None = None

	@field_validator("country_code")
	@classmethod
	def _validate_country_code(cls, value: str | None) -> str | None:
		if value is None:
			return None
		if len(value) != 2 or not (value.isascii() and value.isalpha()):
			raise ValueError("country_code must be a two-letter ISO 3166-1 alpha-2 code")
		return value.lower()


class StoreCreateCustomerAddress(_CustomerAddressPayload):
	"""Body of ``POST /store/customers/me/addresses``."""


class StoreUpdateCustomerAddress(_CustomerAddressPayload):
	"""Body of ``POST /store/customers/me/addresses/{address_id}``."""
