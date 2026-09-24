from typing import Any

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


class ResetPasswordTokenInput(BaseModel):
	"""Identifier used to generate a provider password-reset token."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	identifier: str = Field(min_length=1)
	metadata: dict[str, Any] | None = None


class VerificationTokenInput(BaseModel):
	"""Verification token delivered to the customer out of band."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	token: str = Field(min_length=1)


class VerificationRequestInput(BaseModel):
	"""Identity details used to create a verification code."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	entity_id: str = Field(min_length=1)
	entity_type: str = Field(min_length=1)
	code_provider: str = Field(min_length=1)
	metadata: dict[str, Any] | None = None


class VerificationConfirmInput(BaseModel):
	"""Code submitted to complete identity verification."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	code: str = Field(min_length=1)
	code_provider: str = "token"
