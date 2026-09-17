from typing import Any

import frappe
from frappe.auth import validate_ip_address
from frappe.twofactor import should_run_2fa
from pydantic import ValidationError

from ceto.api.auth.schemas import (
	AuthProvider,
	AuthProvidersListResponse,
	AuthResponse,
	EmailPasswordInput,
)
from ceto.api.auth.tokens import create_customer_token

EMAIL_PASSWORD_PROVIDER = AuthProvider(
	id="emailpass",
	identifier="emailpass",
	display_name="Email and password",
	flow="credentials",
)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def providers() -> dict[str, list[dict[str, str]]]:
	"""List the authentication providers available to customers."""
	response = AuthProvidersListResponse(providers=[EMAIL_PASSWORD_PROVIDER])
	return response.model_dump(mode="json")


@frappe.whitelist(allow_guest=True, methods=["POST"])
def authenticate(auth_provider: str, **credentials: Any) -> dict[str, str]:
	"""Authenticate a customer with a provider and return a Ceto JWT."""
	if auth_provider != EMAIL_PASSWORD_PROVIDER.id:
		frappe.throw(
			f"Authentication provider {auth_provider!r} is not available",
			frappe.ValidationError,
		)

	try:
		data = EmailPasswordInput.model_validate(credentials)
	except ValidationError as exc:
		frappe.throw(_validation_message(exc), frappe.ValidationError)

	if frappe.get_system_settings("disable_user_pass_login"):
		raise frappe.AuthenticationError

	login_manager = frappe.local.login_manager
	login_manager.run_trigger("before_login")
	login_manager.authenticate(user=data.email, pwd=data.password.get_secret_value())

	user_type = frappe.db.get_value("User", login_manager.user, "user_type")
	if user_type != "Website User":
		raise frappe.AuthenticationError

	validate_ip_address(login_manager.user)
	login_manager.validate_hour()
	if login_manager.force_user_to_reset_password() or should_run_2fa(login_manager.user):
		# This endpoint cannot complete Frappe's password-reset or two-factor flows.
		raise frappe.AuthenticationError

	response = AuthResponse(token=create_customer_token(login_manager.user))
	return response.model_dump(mode="json")


def _validation_message(exc: ValidationError) -> str:
	fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
	return f"Invalid authentication input: {fields}"
