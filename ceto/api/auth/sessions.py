from ceto.routing import ceto_router
from ceto.services.auth.sessions import create_customer_session, delete_customer_session
from ceto.types.http.auth import AuthSessionDeleteResponse, AuthSessionResponse, AuthUser


@ceto_router.post("/auth/session")
def create_authentication_session() -> AuthSessionResponse:
	"""Exchange the authenticated customer's bearer token for a cookie session."""
	return AuthSessionResponse(user=AuthUser.model_validate(create_customer_session()))


@ceto_router.delete("/auth/session")
def delete_authentication_session() -> AuthSessionDeleteResponse:
	"""Delete the authenticated customer's cookie session."""
	delete_customer_session()
	return AuthSessionDeleteResponse(success=True)
