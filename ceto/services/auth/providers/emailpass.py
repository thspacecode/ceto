from typing import Any

import frappe
from frappe import _
from frappe.auth import validate_ip_address
from frappe.twofactor import should_run_2fa
from frappe.utils import cint
from frappe.utils.password import delete_login_failed_cache, update_password

from ceto.services.auth.providers.base import AuthenticationResult, CustomerAuthProvider, validate_input
from ceto.services.auth.tokens import (
	create_customer_password_reset_token,
	create_customer_registration_token,
	create_customer_token,
	get_bearer_password_reset_user,
)
from ceto.types.http.auth import EmailPasswordInput, ResetPasswordTokenInput

EMAIL_PASSWORD_PROVIDER_ID = "emailpass"


class EmailPasswordProvider(CustomerAuthProvider):
	identifier = EMAIL_PASSWORD_PROVIDER_ID
	display_name = "Email and password"
	flow = "credentials"

	def authenticate(self, credentials: dict[str, Any]) -> AuthenticationResult:
		data = validate_input(EmailPasswordInput, credentials)
		return AuthenticationResult(
			token=self._authenticate_email_password(
				email=str(data.email),
				password=data.password.get_secret_value(),
			)
		)

	def _authenticate_email_password(self, email: str, password: str) -> str:
		"""Authenticate a website customer with a password and return a signed token."""
		if frappe.get_system_settings("disable_user_pass_login"):
			raise frappe.AuthenticationError

		login_manager = frappe.local.login_manager
		login_manager.run_trigger("before_login")
		login_manager.authenticate(user=email, pwd=password)

		user_type = frappe.db.get_value("User", login_manager.user, "user_type")
		if user_type != "Website User":
			raise frappe.AuthenticationError

		validate_ip_address(login_manager.user)
		login_manager.validate_hour()
		if login_manager.force_user_to_reset_password() or should_run_2fa(login_manager.user):
			# This endpoint cannot complete Frappe's password-reset or two-factor flows.
			raise frappe.AuthenticationError

		return create_customer_token(login_manager.user)

	def register(self, credentials: dict[str, Any]) -> AuthenticationResult:
		"""Validate registration credentials and return a single-purpose registration token."""
		data = validate_input(EmailPasswordInput, credentials)
		email = str(data.email).lower()

		if frappe.db.exists("User", email):
			frappe.throw(f"Customer {email} is already registered", frappe.DuplicateEntryError)
		_validate_password_policy(email, data.password.get_secret_value())

		return AuthenticationResult(token=create_customer_registration_token(email))

	def reset_password(self, payload: dict[str, Any]) -> None:
		"""Generate a password-reset token and hand it to configured subscribers.

		The response is deliberately identical for known and unknown identifiers so
		the endpoint cannot be used to enumerate registered customers.
		"""
		data = validate_input(ResetPasswordTokenInput, payload)
		identifier = data.identifier.strip().lower()

		user = frappe.db.get_value("User", identifier, ["enabled", "user_type"], as_dict=True)
		if not user or not user.enabled or user.user_type != "Website User":
			return

		token = create_customer_password_reset_token(identifier)
		for method in frappe.get_hooks("ceto_auth_password_reset", []):
			# Hook paths come exclusively from installed-app configuration. This is the
			# standard Frappe extension boundary, not request-controlled dynamic code.
			frappe.call(
				frappe.get_attr(method),  # nosemgrep: frappe-codeinjection-eval
				identifier=identifier,
				token=token,
				metadata=data.metadata or {},
			)

	def update_credentials(self, credentials: dict[str, Any]) -> bool:
		"""Reset the customer's password using the request's reset-password token."""
		data = validate_input(EmailPasswordInput, credentials)
		user = get_bearer_password_reset_user()

		if str(data.email).lower() != user.lower():
			frappe.throw("Email does not match the reset-password token", frappe.ValidationError)
		_validate_password_policy(user, data.password.get_secret_value())

		update_password(user, data.password.get_secret_value(), logout_all_sessions=True)
		frappe.db.set_value("User", user, "reset_password_key", "")
		delete_login_failed_cache(user)
		return True


def _validate_password_policy(email: str, password: str) -> None:
	"""Enforce the site's password strength policy exactly as Frappe signups do."""
	from frappe.utils.password_strength import test_password_strength

	if frappe.get_system_settings("enable_password_policy"):
		result = test_password_strength(password, user_inputs=[email])
		minimum_score = cint(frappe.get_system_settings("minimum_password_score"))
		if result and (result.get("score") or 0) < minimum_score:
			frappe.throw(_("Invalid Password"), frappe.ValidationError)
