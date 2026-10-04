"""Pinned Medusa Store Customer query parameters (Phase 0 contract).

Mirrors the pinned ``StoreGetCustomerParams``, ``StoreGetCustomerAddressParams``
and ``StoreCustomerAddressFilters`` of the ``HttpTypes`` of
``@medusajs/types@2.21.1`` (``http/customer/store``), plus the domain-neutral
``SelectParams`` / ``FindParams`` shapes of ``http/common`` they extend.

Unknown query parameters are rejected, like every Ceto contract. The pinned
``StoreCustomerAddressFilters`` deliberately drops ``company`` and ``province``
from the base address filters (pinned ``Omit``), so Ceto rejects them too.
Filters accept the single-value member of the pinned ``string | string[]``
unions only: the address book of one customer is a bounded per-user list where
an array filter has no storefront use (same single-member policy as the cart
shipping-methods body).
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StoreCustomerSelectParams(BaseModel):
	"""The domain-neutral Medusa ``SelectParams`` fields selector.

	Mirrors ``SelectParams`` of ``http/common`` in the pinned
	``@medusajs/types@2.21.1``: a comma-separated field/relation selector
	(e.g. ``fields=id,email``). Applies to every customer and address route
	except the delete route, whose response shape is fixed.
	"""

	model_config = ConfigDict(extra="forbid")

	fields: str | None = None


class StoreCustomerFindParams(StoreCustomerSelectParams):
	"""The domain-neutral Medusa ``FindParams`` pagination selector.

	Mirrors ``FindParams`` of ``http/common`` in the pinned
	``@medusajs/types@2.21.1``. The window bounds are Ceto policy (not
	Medusa-derived): ``offset`` starts at 0 and ``limit`` defaults to 20 with
	a maximum of 100 — enforced by the implementing phase, validated here.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int | None = Field(default=None, ge=1, le=100)
	offset: int | None = Field(default=None, ge=0)
	order: str | None = None
	with_deleted: bool | None = None


class StoreGetCustomerParams(StoreCustomerSelectParams):
	"""Query of ``GET /store/customers/me``."""


class StoreGetCustomerAddressParams(StoreCustomerSelectParams):
	"""Query of ``GET /store/customers/me/addresses/{address_id}``."""


class StoreCustomerAddressFilters(StoreCustomerFindParams):
	"""Query of ``GET /store/customers/me/addresses``.

	Mirrors the pinned ``StoreCustomerAddressFilters`` of
	``@medusajs/types@2.21.1``: the searchable address columns plus the
	``FindParams`` window. ``company`` and ``province`` are omitted by the
	pinned type and therefore rejected here.
	"""

	model_config = ConfigDict(extra="forbid")

	q: str | None = None
	city: str | None = None
	country_code: str | None = None
	postal_code: str | None = None

	@field_validator("country_code")
	@classmethod
	def _validate_country_code(cls, value: str | None) -> str | None:
		if value is None:
			return None
		if len(value) != 2 or not (value.isascii() and value.isalpha()):
			raise ValueError("country_code must be a two-letter ISO 3166-1 alpha-2 code")
		return value.lower()
