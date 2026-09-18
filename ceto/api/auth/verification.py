from typing import Any

from werkzeug.wrappers import Response

from ceto.routing import ceto_router
from ceto.services.auth.verification import confirm_verification, request_verification
from ceto.types.http.auth import VerificationConfirmInput, VerificationRequestInput


@ceto_router.post("/auth/verification/request", allow_guest=True)
def request_customer_verification(**payload: Any) -> Response:
	"""Create a customer verification request."""
	data = VerificationRequestInput.model_validate(payload)
	request_verification(
		entity_id=data.entity_id,
		entity_type=data.entity_type,
		code_provider=data.code_provider,
		metadata=data.metadata,
	)
	return Response(status=201)


@ceto_router.post("/auth/verification/confirm", allow_guest=True)
def confirm_customer_verification(**payload: Any) -> Response:
	"""Confirm and consume a customer verification code."""
	data = VerificationConfirmInput.model_validate(payload)
	confirm_verification(code=data.code, code_provider=data.code_provider)
	return Response(status=200)
