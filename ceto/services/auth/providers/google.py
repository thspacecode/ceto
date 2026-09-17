from typing import Any

import frappe

from ceto.services.auth.oauth import complete_google_auth, start_google_auth
from ceto.services.auth.providers.base import AuthenticationResult, CustomerAuthProvider, validate_input
from ceto.types.http.auth import GoogleOAuthInput, OAuthCallbackInput

GOOGLE_PROVIDER_ID = "google"


class GoogleProvider(CustomerAuthProvider):
	identifier = GOOGLE_PROVIDER_ID
	display_name = "Google"
	flow = "redirect"

	def is_enabled(self) -> bool:
		provider = frappe.db.get_value(
			"Social Login Key",
			self.identifier,
			["enable_social_login", "client_id"],
			as_dict=True,
		)
		return bool(provider and provider.enable_social_login and provider.client_id)

	def authenticate(self, credentials: dict[str, Any]) -> AuthenticationResult:
		data = validate_input(GoogleOAuthInput, credentials)
		return AuthenticationResult(location=start_google_auth(str(data.callback_url)))

	def validate_callback(self, callback: dict[str, Any]) -> AuthenticationResult:
		data = validate_input(OAuthCallbackInput, callback)
		return AuthenticationResult(token=complete_google_auth(code=data.code, state=data.state))
