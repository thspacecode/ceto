from typing import Literal

from pydantic import BaseModel


class AuthProvider(BaseModel):
	"""Public information about an authentication provider."""

	id: str
	identifier: str
	display_name: str
	flow: Literal["credentials", "redirect"]
