EMAIL_PASSWORD_PROVIDER_ID = "emailpass"

_EMAIL_PASSWORD_PROVIDER = {
	"id": EMAIL_PASSWORD_PROVIDER_ID,
	"identifier": EMAIL_PASSWORD_PROVIDER_ID,
	"display_name": "Email and password",
	"flow": "credentials",
}


def get_customer_auth_providers() -> list[dict[str, str]]:
	"""Return public metadata for the supported customer auth providers."""
	return [_EMAIL_PASSWORD_PROVIDER.copy()]
