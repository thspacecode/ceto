from typing import Any

import frappe
from pydantic import ValidationError

from ceto.api.auth.schemas import AuthProvidersListResponse, AuthResponse, EmailPasswordInput
from ceto.routing import router
from ceto.services.auth.customer import authenticate_customer, get_customer_auth_providers


@router.get("/auth/customer/providers", allow_guest=True)
def providers() -> dict[str, list[dict[str, str]]]:
	"""List the authentication providers available to customers."""
	response = AuthProvidersListResponse(providers=get_customer_auth_providers())
	return response.model_dump(mode="json")


@router.post("/auth/customer/{auth_provider}", allow_guest=True)
def authenticate(auth_provider: str, **credentials: Any) -> dict[str, str]:
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
	return AuthResponse(token=token).model_dump(mode="json")


def _validation_message(exc: ValidationError) -> str:
	fields = ", ".join(".".join(str(part) for part in error["loc"]) for error in exc.errors())
	return f"Invalid authentication input: {fields}"
