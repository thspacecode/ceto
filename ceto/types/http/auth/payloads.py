from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, SecretStr


class EmailPasswordInput(BaseModel):
	"""Credentials accepted by the email-password provider."""

	model_config = ConfigDict(extra="forbid")

	email: EmailStr
	password: SecretStr = Field(min_length=1)


class GoogleOAuthInput(BaseModel):
	"""Input used to begin Google's authorization-code flow."""

	model_config = ConfigDict(extra="forbid")

	callback_url: HttpUrl


class OAuthCallbackInput(BaseModel):
	"""Authorization response returned by an OAuth provider."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	code: str = Field(min_length=1)
	state: str = Field(min_length=1)
