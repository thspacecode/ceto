from typing import Any

import frappe
from pydantic import BaseModel, ValidationError

from ceto.routing import JSON, store_router
from ceto.services.auth.authentication import authenticate_customer
from ceto.services.auth.oauth import complete_google_auth, start_google_auth
from ceto.services.auth.providers import EMAIL_PASSWORD_PROVIDER_ID, GOOGLE_PROVIDER_ID
from ceto.types.http.auth import (
	AuthRedirectResponse,
	AuthResponse,
	EmailPasswordInput,
	GoogleOAuthInput,
	OAuthCallbackInput,
)


@store_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> JSON[AuthResponse | AuthRedirectResponse]:
	"""Authenticate with credentials or begin a provider redirect flow."""
	if auth_provider == EMAIL_PASSWORD_PROVIDER_ID:
		data = _validate(EmailPasswordInput, credentials)
		token = authenticate_customer(
			auth_provider=auth_provider,
			email=data.email,
			password=data.password.get_secret_value(),
		)
		return AuthResponse(token=token).to_json()

	if auth_provider == GOOGLE_PROVIDER_ID:
		data = _validate(GoogleOAuthInput, credentials)
		location = start_google_auth(str(data.callback_url))
		return AuthRedirectResponse(location=location).to_json()

	frappe.throw(
		f"Authentication provider {auth_provider!r} is not available",
		frappe.ValidationError,
	)


@store_router.post("/auth/customer/{auth_provider}/callback", allow_guest=True)
def authenticate_callback(auth_provider: str, **callback: Any) -> JSON[AuthResponse]:
	"""Complete a provider redirect flow and return a Ceto JWT."""
	if auth_provider != GOOGLE_PROVIDER_ID:
		frappe.throw(
			f"Authentication provider {auth_provider!r} is not available",
			frappe.ValidationError,
		)

	data = _validate(OAuthCallbackInput, callback)
	token = complete_google_auth(code=data.code, state=data.state)
	return AuthResponse(token=token).to_json()


def _validate[Model: BaseModel](model: type[Model], values: dict[str, Any]) -> Model:
	try:
		return model.model_validate(values)
	except ValidationError as exc:
		frappe.throw(_validation_message(exc), frappe.ValidationError)


def _validation_message(exc: ValidationError) -> str:
	fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
	return f"Invalid authentication input: {fields}"
