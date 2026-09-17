from ceto.routing.response import JSONModel
from ceto.types.http.auth.entities import AuthProvider


class AuthProvidersListResponse(JSONModel):
	"""Authentication providers available for an actor type."""

	providers: list[AuthProvider]


class AuthResponse(JSONModel):
	"""Successful authentication token response."""

	token: str


class AuthRedirectResponse(JSONModel):
	"""Location at which the client should continue an OAuth flow."""

	location: str
