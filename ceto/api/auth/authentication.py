from typing import Any

from ceto.routing import JSON, ceto_router
from ceto.services.auth.providers import get_customer_auth_provider
from ceto.types.http.auth import AuthRedirectResponse, AuthResponse


@ceto_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> JSON[AuthRedirectResponse | AuthResponse]:
	"""Authenticate with credentials or begin a provider redirect flow."""
	provider = get_customer_auth_provider(auth_provider)
	return provider.authenticate(credentials).to_response()


@ceto_router.post("/auth/customer/{auth_provider}/callback", allow_guest=True)
def authenticate_callback(auth_provider: str, **callback: Any) -> JSON[AuthRedirectResponse | AuthResponse]:
	"""Complete a provider redirect flow and return its authentication result."""
	provider = get_customer_auth_provider(auth_provider)
	return provider.validate_callback(callback).to_response()
