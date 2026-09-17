from pydantic import BaseModel, ConfigDict, Field, SecretStr


class EmailPasswordInput(BaseModel):
	"""Credentials accepted by the email-password provider."""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	email: str = Field(min_length=1)
	password: SecretStr = Field(min_length=1)
