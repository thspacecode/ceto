from typing import Any

from ceto.routing import JSON, store_router
from ceto.services.auth.providers import AuthenticationResult, get_customer_auth_provider
from ceto.types.http.auth import AuthRedirectResponse, AuthResponse


@store_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> JSON[AuthResponse | AuthRedirectResponse]:
	"""Authenticate with credentials or begin a provider redirect flow."""
	provider = get_customer_auth_provider(auth_provider)
	return _authentication_response(provider.authenticate(credentials))


@store_router.post("/auth/customer/{auth_provider}/callback", allow_guest=True)
def authenticate_callback(auth_provider: str, **callback: Any) -> JSON[AuthResponse | AuthRedirectResponse]:
	"""Complete a provider redirect flow and return its authentication result."""
	provider = get_customer_auth_provider(auth_provider)
	return _authentication_response(provider.validate_callback(callback))


def _authentication_response(result: AuthenticationResult) -> JSON[AuthResponse | AuthRedirectResponse]:
	if result.location is not None:
		return AuthRedirectResponse(location=result.location).to_json()
	assert result.token is not None
	return AuthResponse(token=result.token).to_json()
