from ceto.routing import JSON, store_router
from ceto.services.auth.providers import get_customer_auth_providers
from ceto.types.http.auth import AuthProvidersListResponse


@store_router.get("/auth/customer/providers", allow_guest=True)
def list_customer_auth_providers() -> JSON[AuthProvidersListResponse]:
	"""List the authentication providers available to customers."""
	response = AuthProvidersListResponse(providers=get_customer_auth_providers())
	return response.to_json()
