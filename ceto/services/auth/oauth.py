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

from ceto.services.auth.providers import GOOGLE_PROVIDER_ID, is_google_auth_enabled
from ceto.services.auth.tokens import create_customer_token

_OAUTH_STATE_TTL_SECONDS = 600
_OAUTH_STATE_KEY_PREFIX = "ceto:oauth:google:"


def start_google_auth(callback_url: str) -> str:
	"""Create a short-lived OAuth state and return Google's authorization URL."""
	_require_google_auth()

	state = frappe.generate_hash(length=40)
	frappe.cache.set_value(
		_state_key(state),
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


def complete_google_auth(code: str, state: str) -> str:
	"""Exchange Google's callback code, provision the customer, and return a Ceto JWT."""
	_require_google_auth()
	callback_url = _consume_callback_url(state)

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


def _consume_callback_url(state: str) -> str:
	key = _state_key(state)
	data = frappe.cache.get_value(key, expires=True, use_local_cache=False)
	if data:
		frappe.cache.delete_value(key)
	if not isinstance(data, dict) or not data.get("callback_url"):
		frappe.throw(_("Invalid or expired OAuth state"), frappe.AuthenticationError)
	return data["callback_url"]


def _require_google_auth() -> None:
	if not is_google_auth_enabled():
		frappe.throw(_("Google authentication is not available"), frappe.ValidationError)


def _state_key(state: str) -> str:
	return f"{_OAUTH_STATE_KEY_PREFIX}{state}"
