from typing import Any

from ceto.routing import JSONModel, store_router
from ceto.services.auth.providers import get_customer_auth_provider


@store_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> JSONModel:
	"""Authenticate with credentials or begin a provider redirect flow."""
	provider = get_customer_auth_provider(auth_provider)
	return provider.authenticate(credentials).to_response()


@store_router.post("/auth/customer/{auth_provider}/callback", allow_guest=True)
def authenticate_callback(auth_provider: str, **callback: Any) -> JSONModel:
	"""Complete a provider redirect flow and return its authentication result."""
	provider = get_customer_auth_provider(auth_provider)
	return provider.validate_callback(callback).to_response()
