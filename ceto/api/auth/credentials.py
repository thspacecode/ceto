"""Customer credential lifecycle endpoints (register, reset, update)."""

from typing import Any

from werkzeug.wrappers import Response

from ceto.routing import JSON, ceto_router
from ceto.services.auth.providers import get_customer_auth_provider
from ceto.types.http.auth import AuthRedirectResponse, AuthResponse, AuthSuccessResponse


@ceto_router.post("/auth/customer/{auth_provider}/register", allow_guest=True)
def register_customer(auth_provider: str, **credentials: Any) -> JSON[AuthRedirectResponse | AuthResponse]:
	"""Validate registration credentials and return a registration token."""
	provider = get_customer_auth_provider(auth_provider)
	return provider.register(credentials).to_response()


@ceto_router.post("/auth/customer/{auth_provider}/reset-password", allow_guest=True)
def generate_customer_password_reset_token(auth_provider: str, **payload: Any) -> Response:
	"""Generate a password-reset token and deliver it to configured subscribers."""
	provider = get_customer_auth_provider(auth_provider)
	provider.reset_password(payload)
	return Response(status=200)


@ceto_router.post("/auth/customer/{auth_provider}/update", allow_guest=True)
def update_customer_authentication(auth_provider: str, **credentials: Any) -> AuthSuccessResponse:
	"""Update credentials using the request's single-purpose bearer token."""
	provider = get_customer_auth_provider(auth_provider)
	return AuthSuccessResponse(success=provider.update_credentials(credentials))
