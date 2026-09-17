import pickle
from typing import Any

import frappe
from frappe import _
from frappe.integrations.oauth2_logins import decoder_compat
from frappe.utils.oauth import (
	SignupDisabledError,
	get_email,
	get_oauth2_flow,
	get_oauth2_providers,
	update_oauth_user,
)
from redis.exceptions import ConnectionError

from ceto.services.auth.providers.base import AuthenticationResult, CustomerAuthProvider, validate_input
from ceto.services.auth.tokens import create_customer_token
from ceto.types.http.auth import GoogleOAuthInput, OAuthCallbackInput

GOOGLE_PROVIDER_ID = "google"
_OAUTH_STATE_TTL_SECONDS = 600
_OAUTH_STATE_KEY_PREFIX = "ceto:oauth:google:"


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
		return AuthenticationResult(location=self._start_auth(str(data.callback_url)))

	def validate_callback(self, callback: dict[str, Any]) -> AuthenticationResult:
		data = validate_input(OAuthCallbackInput, callback)
		return AuthenticationResult(token=self._complete_auth(code=data.code, state=data.state))

	def _start_auth(self, callback_url: str) -> str:
		"""Create a short-lived OAuth state and return Google's authorization URL."""
		state = frappe.generate_hash(length=40)
		frappe.cache.set_value(
			self._state_key(state),
			{"callback_url": callback_url},
			expires_in_sec=_OAUTH_STATE_TTL_SECONDS,
		)

		provider = get_oauth2_providers()[GOOGLE_PROVIDER_ID]
		params = provider.get("auth_url_data", {}).copy()
		params.update(
			{
				"redirect_uri": callback_url,
				"state": state,
			}
		)
		return get_oauth2_flow(GOOGLE_PROVIDER_ID).get_authorize_url(**params)

	def _complete_auth(self, code: str, state: str) -> str:
		"""Exchange Google's callback code, provision the customer, and return a Ceto JWT."""
		callback_url = self._consume_callback_url(state)

		flow = get_oauth2_flow(GOOGLE_PROVIDER_ID)
		provider = get_oauth2_providers()[GOOGLE_PROVIDER_ID]
		session = flow.get_auth_session(
			data={
				"code": code,
				"redirect_uri": callback_url,
				"grant_type": "authorization_code",
			},
			decoder=decoder_compat,
		)
		info = session.get(
			provider["api_endpoint"],
			params=provider.get("api_endpoint_args"),
		).json()

		email = get_email(info)
		if not info.get("email_verified") or not email:
			frappe.throw(_("Email not verified with Google"), frappe.AuthenticationError)

		email = email.lower()
		existing_user_type = frappe.db.get_value("User", email, "user_type")
		if existing_user_type and existing_user_type != "Website User":
			raise frappe.AuthenticationError

		try:
			updated = update_oauth_user(email, info, GOOGLE_PROVIDER_ID)
		except SignupDisabledError:
			raise frappe.PermissionError(_("Signup is disabled"))

		if updated is False:
			raise frappe.AuthenticationError

		user = frappe.db.get_value("User", email, ["enabled", "user_type"], as_dict=True)
		if not user or not user.enabled or user.user_type != "Website User":
			raise frappe.AuthenticationError

		return create_customer_token(email)

	@classmethod
	def _consume_callback_url(cls, state: str) -> str:
		"""Atomically consume an OAuth state value from Redis."""
		cache_key = frappe.cache.make_key(cls._state_key(state))
		try:
			serialized = frappe.cache.getdel(cache_key)
		except ConnectionError:
			serialized = None
		frappe.local.cache.pop(cache_key, None)

		data = pickle.loads(serialized) if serialized is not None else None
		if not isinstance(data, dict) or not data.get("callback_url"):
			frappe.throw(_("Invalid or expired OAuth state"), frappe.AuthenticationError)
		return data["callback_url"]

	@staticmethod
	def _state_key(state: str) -> str:
		return f"{_OAUTH_STATE_KEY_PREFIX}{state}"
