import frappe

from ceto.services.auth.providers.base import AuthenticationResult, CustomerAuthProvider
from ceto.services.auth.providers.emailpass import EMAIL_PASSWORD_PROVIDER_ID, EmailPasswordProvider
from ceto.services.auth.providers.google import GOOGLE_PROVIDER_ID, GoogleProvider

_PROVIDERS: dict[str, CustomerAuthProvider] = {
	provider.identifier: provider
	for provider in (
		EmailPasswordProvider(),
		GoogleProvider(),
	)
}


def get_customer_auth_provider(identifier: str) -> CustomerAuthProvider:
	"""Resolve an enabled customer auth provider by its public identifier."""
	provider = _PROVIDERS.get(identifier)
	if provider is None or not provider.is_enabled():
		frappe.throw(
			f"Authentication provider {identifier!r} is not available",
			frappe.ValidationError,
		)
	return provider


def get_customer_auth_providers() -> list[dict[str, str]]:
	"""Return public metadata for every enabled customer auth provider."""
	return [provider.public_info() for provider in _PROVIDERS.values() if provider.is_enabled()]


__all__ = [
	"EMAIL_PASSWORD_PROVIDER_ID",
	"GOOGLE_PROVIDER_ID",
	"AuthenticationResult",
	"CustomerAuthProvider",
	"get_customer_auth_provider",
	"get_customer_auth_providers",
]
