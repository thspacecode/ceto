from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

import frappe
from pydantic import BaseModel, ValidationError

AuthFlow = Literal["credentials", "redirect"]


@dataclass(frozen=True)
class AuthenticationResult:
	"""Provider-independent result returned to the authentication endpoint."""

	token: str | None = None
	location: str | None = None

	def __post_init__(self) -> None:
		if (self.token is None) == (self.location is None):
			raise ValueError("Authentication result must contain exactly one of token or location")


class CustomerAuthProvider(ABC):
	"""Contract implemented by every customer authentication provider."""

	identifier: str
	display_name: str
	flow: AuthFlow

	def is_enabled(self) -> bool:
		return True

	def public_info(self) -> dict[str, str]:
		return {
			"id": self.identifier,
			"identifier": self.identifier,
			"display_name": self.display_name,
			"flow": self.flow,
		}

	@abstractmethod
	def authenticate(self, credentials: dict[str, Any]) -> AuthenticationResult:
		"""Authenticate directly or begin a redirect flow."""

	def validate_callback(self, callback: dict[str, Any]) -> AuthenticationResult:
		frappe.throw(
			f"Authentication provider {self.identifier!r} does not support callbacks",
			frappe.ValidationError,
		)


def validate_input[Model: BaseModel](model: type[Model], values: dict[str, Any]) -> Model:
	try:
		return model.model_validate(values)
	except ValidationError as exc:
		fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
		frappe.throw(f"Invalid authentication input: {fields}", frappe.ValidationError)
