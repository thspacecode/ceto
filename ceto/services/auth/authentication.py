import frappe
from frappe.auth import validate_ip_address
from frappe.twofactor import should_run_2fa

from ceto.services.auth.providers import EMAIL_PASSWORD_PROVIDER_ID
from ceto.services.auth.tokens import create_customer_token


def authenticate_customer(auth_provider: str, email: str, password: str) -> str:
	"""Authenticate a website customer and return a signed customer token."""
	if auth_provider != EMAIL_PASSWORD_PROVIDER_ID:
		frappe.throw(
			f"Authentication provider {auth_provider!r} is not available",
			frappe.ValidationError,
		)

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
