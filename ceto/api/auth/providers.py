from ceto.routing import store_router
from ceto.services.auth.providers import get_customer_auth_providers
from ceto.types.http.auth import AuthProvidersListResponse


@store_router.get("/auth/customer/providers", allow_guest=True)
def list_customer_auth_providers() -> AuthProvidersListResponse:
	"""List the authentication providers available to customers."""
	return AuthProvidersListResponse(providers=get_customer_auth_providers())
