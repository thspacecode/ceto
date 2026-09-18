import frappe

from ceto.routing import ceto_router
from ceto.services.auth.tokens import refresh_customer_token
from ceto.types.http.auth import AuthResponse


@ceto_router.post("/auth/token/refresh")
def refresh_authentication_token() -> AuthResponse:
	"""Issue a fresh bearer token for the authenticated customer."""
	return AuthResponse(token=refresh_customer_token(frappe.session.user))
