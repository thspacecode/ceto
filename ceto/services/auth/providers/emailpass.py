from typing import Any

from ceto.services.auth.authentication import authenticate_email_password
from ceto.services.auth.providers.base import AuthenticationResult, CustomerAuthProvider, validate_input
from ceto.types.http.auth import EmailPasswordInput

EMAIL_PASSWORD_PROVIDER_ID = "emailpass"


class EmailPasswordProvider(CustomerAuthProvider):
	identifier = EMAIL_PASSWORD_PROVIDER_ID
	display_name = "Email and password"
	flow = "credentials"

	def authenticate(self, credentials: dict[str, Any]) -> AuthenticationResult:
		data = validate_input(EmailPasswordInput, credentials)
		token = authenticate_email_password(
			email=data.email,
			password=data.password.get_secret_value(),
		)
		return AuthenticationResult(token=token)
