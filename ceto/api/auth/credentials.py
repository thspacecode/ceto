"""Customer credential lifecycle endpoints (register, reset, update)."""

from typing import Any

import frappe
from werkzeug.wrappers import Response

from ceto.routing import JSON, ceto_router
from ceto.routing.exceptions import InvalidDataError
from ceto.services.auth.providers import get_customer_auth_provider
from ceto.types.http.auth import AuthRedirectResponse, AuthResponse, AuthSuccessResponse


@ceto_router.post("/auth/customer/{auth_provider}/register", allow_guest=True)
def register_customer(auth_provider: str, **credentials: Any) -> JSON[AuthRedirectResponse | AuthResponse]:
	"""Validate registration credentials and return a registration token."""
	provider = get_customer_auth_provider(auth_provider)
	try:
		return provider.register(credentials).to_response()
	except frappe.DuplicateEntryError as exc:
		# A duplicate registration identity is an expected client conflict,
		# not a server failure: this boundary renders it as the stable 400
		# invalid_data body. The translation is deliberately scoped to this
		# route — a global router mapping would also rebrand genuine
		# storage-level duplicates elsewhere (id collisions) as client
		# errors and hide them from the error log.
		raise InvalidDataError(str(exc) or None) from None


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
