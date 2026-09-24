from typing import Literal

from pydantic import BaseModel, Field


class AuthProvider(BaseModel):
	"""Public information about an authentication provider."""

	id: str
	identifier: str
	display_name: str
	flow: Literal["credentials", "redirect"]


class AuthUser(BaseModel):
	"""Customer identity returned when a cookie session is created."""

	id: str
	email: str
	first_name: str = ""
	last_name: str = ""
	company_name: str = ""
	default_billing_address_id: str | None = None
	default_shipping_address_id: str | None = None
	addresses: list[dict[str, object]] = Field(default_factory=list)
