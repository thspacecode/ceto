from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from ceto.routing.response import JSONModel


class AuthProvider(BaseModel):
	id: str
	identifier: str
	display_name: str
	flow: Literal["credentials", "redirect"]


class AuthProvidersListResponse(JSONModel):
	providers: list[AuthProvider]


class EmailPasswordInput(BaseModel):
	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	email: str = Field(min_length=1)
	password: SecretStr = Field(min_length=1)


class AuthResponse(JSONModel):
	token: str
