from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import frappe
from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
	from ceto.routing.response import JSON
	from ceto.types.http.auth import AuthRedirectResponse, AuthResponse

AuthFlow = Literal["credentials", "redirect"]


@dataclass(frozen=True)
class AuthenticationResult:
	"""Provider-independent result returned to the authentication endpoint."""

	token: str | None = None
	location: str | None = None

	def __post_init__(self) -> None:
		if (self.token is None) == (self.location is None):
			raise ValueError("Authentication result must contain exactly one of token or location")

	def to_response(self) -> "JSON[AuthRedirectResponse | AuthResponse]":
		"""Convert the provider result to its typed public HTTP response."""
		from ceto.types.http.auth import AuthRedirectResponse, AuthResponse

		if self.location is not None:
			return AuthRedirectResponse(location=self.location).to_json()
		assert self.token is not None
		return AuthResponse(token=self.token).to_json()


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

	def register(self, credentials: dict[str, Any]) -> AuthenticationResult:
		"""Register credentials with the provider and return a registration token."""
		frappe.throw(
			f"Authentication provider {self.identifier!r} does not support registration",
			frappe.ValidationError,
		)

	def reset_password(self, payload: dict[str, Any]) -> None:
		"""Generate a password-reset token and notify configured subscribers."""
		frappe.throw(
			f"Authentication provider {self.identifier!r} does not support password resets",
			frappe.ValidationError,
		)

	def update_credentials(self, credentials: dict[str, Any]) -> bool:
		"""Update credentials using the request's single-purpose bearer token."""
		frappe.throw(
			f"Authentication provider {self.identifier!r} does not support credential updates",
			frappe.ValidationError,
		)


def validate_input[Model: BaseModel](model: type[Model], values: dict[str, Any]) -> Model:
	try:
		return model.model_validate(values)
	except ValidationError as exc:
		fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
		frappe.throw(f"Invalid authentication input: {fields}", frappe.ValidationError)
