import frappe

EMAIL_PASSWORD_PROVIDER_ID = "emailpass"
GOOGLE_PROVIDER_ID = "google"

_EMAIL_PASSWORD_PROVIDER = {
	"id": EMAIL_PASSWORD_PROVIDER_ID,
	"identifier": EMAIL_PASSWORD_PROVIDER_ID,
	"display_name": "Email and password",
	"flow": "credentials",
}

_GOOGLE_PROVIDER = {
	"id": GOOGLE_PROVIDER_ID,
	"identifier": GOOGLE_PROVIDER_ID,
	"display_name": "Google",
	"flow": "redirect",
}


def get_customer_auth_providers() -> list[dict[str, str]]:
	"""Return public metadata for the configured customer auth providers."""
	providers = [_EMAIL_PASSWORD_PROVIDER.copy()]
	if is_google_auth_enabled():
		providers.append(_GOOGLE_PROVIDER.copy())
	return providers


def is_google_auth_enabled() -> bool:
	"""Return whether Frappe's Google Social Login Key is ready for use."""
	provider = frappe.db.get_value(
		"Social Login Key",
		GOOGLE_PROVIDER_ID,
		["enable_social_login", "client_id"],
		as_dict=True,
	)
	return bool(provider and provider.enable_social_login and provider.client_id)
