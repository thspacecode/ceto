from typing import Any

import frappe
from pydantic import ValidationError

from ceto.routing import JSON, store_router
from ceto.services.auth.authentication import authenticate_customer
from ceto.types.http.auth import AuthResponse, EmailPasswordInput


@store_router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> JSON[AuthResponse]:
	"""Authenticate a customer with a provider and return a Ceto JWT."""
	try:
		data = EmailPasswordInput.model_validate(credentials)
	except ValidationError as exc:
		frappe.throw(_validation_message(exc), frappe.ValidationError)

	token = authenticate_customer(
		auth_provider=auth_provider,
		email=data.email,
		password=data.password.get_secret_value(),
	)
	return AuthResponse(token=token).to_json()


def _validation_message(exc: ValidationError) -> str:
	fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
	return f"Invalid authentication input: {fields}"
