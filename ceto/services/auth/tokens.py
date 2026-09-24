import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import frappe
import jwt
from frappe.utils import cint

ISSUER = "ceto"
ALGORITHM = "HS256"
DEFAULT_TOKEN_EXPIRY_SECONDS = 24 * 60 * 60
DEFAULT_PASSWORD_RESET_EXPIRY_SECONDS = 60 * 60
DEFAULT_REGISTRATION_EXPIRY_SECONDS = 60 * 60
AUTH_PURPOSE = "auth"
PASSWORD_RESET_PURPOSE = "password_reset"
REGISTRATION_PURPOSE = "registration"
# Purposes that are valid signed customer tokens but never authenticate a request.
# They are consumed only by their dedicated endpoints.
_NON_AUTH_PURPOSES = (PASSWORD_RESET_PURPOSE, REGISTRATION_PURPOSE)
_HKDF_SALT = b"ceto-jwt-hkdf-sha256-v1"
_HKDF_INFO = b"ceto/customer-token/hs256"


def create_customer_token(user: str, *, purpose: str = AUTH_PURPOSE) -> str:
	"""Create the bearer token returned by the Medusa-compatible auth endpoint."""
	now = datetime.now(UTC)
	return jwt.encode(
		{
			"sub": user,
			"actor_type": "customer",
			"purpose": purpose,
			"iss": ISSUER,
			"iat": now,
			"exp": now + timedelta(seconds=_token_expiry_seconds(purpose)),
			"jti": uuid.uuid4().hex,
		},
		_jwt_secret(),
		algorithm=ALGORITHM,
	)


def create_customer_password_reset_token(user: str) -> str:
	"""Create the single-purpose token consumed by the reset-password ``update`` route."""
	return create_customer_token(user, purpose=PASSWORD_RESET_PURPOSE)


def create_customer_registration_token(user: str) -> str:
	"""Create the single-purpose token used to create the customer after registration."""
	return create_customer_token(user, purpose=REGISTRATION_PURPOSE)


def refresh_customer_token(user: str) -> str:
	"""Issue a new token only for an enabled website customer."""
	user_details = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise frappe.AuthenticationError
	return create_customer_token(user)


def decode_customer_token(token: str, *, purpose: str = AUTH_PURPOSE) -> dict:
	"""Validate a Ceto customer token of the expected purpose and return its claims."""
	claims = _decode_signed_customer_token(token)
	if claims.get("purpose", AUTH_PURPOSE) != purpose:
		raise jwt.InvalidTokenError("Invalid token purpose")
	return claims


def _decode_signed_customer_token(token: str) -> dict:
	"""Validate signature, expiry, issuer, and actor type without checking purpose."""
	claims = jwt.decode(
		token,
		_jwt_secret(),
		algorithms=[ALGORITHM],
		issuer=ISSUER,
		options={"require": ["sub", "actor_type", "iss", "iat", "exp"]},
	)
	if claims.get("actor_type") != "customer":
		raise jwt.InvalidTokenError("Invalid actor type")
	return claims


def authenticate_bearer_token() -> None:
	"""Authenticate Ceto JWTs supplied as ``Authorization: Bearer`` tokens."""
	if frappe.session.user not in ("", "Guest"):
		return

	# OAuth access tokens are also Bearer tokens. Only claim JWT-shaped values;
	# otherwise let Frappe's other authentication handlers process the request.
	token = _get_bearer_token()
	if not token:
		return

	try:
		claims = decode_customer_token(token)
	except jwt.InvalidTokenError:
		# Valid signed customer tokens with a non-auth purpose are consumed by their
		# dedicated endpoints; they must not authenticate arbitrary requests.
		try:
			claims = _decode_signed_customer_token(token)
		except jwt.InvalidTokenError:
			raise frappe.AuthenticationError from None
		if claims.get("purpose") not in _NON_AUTH_PURPOSES:
			raise frappe.AuthenticationError
		return

	# The signed token's subject is accepted only after issuer, actor type, expiry,
	# and purpose validation above; _validate_website_customer re-checks enabled
	# state and Website User type against the database.
	frappe.set_user(_validate_website_customer(claims["sub"]))  # nosemgrep: frappe-setuser


def _jwt_secret() -> str:
	if secret := frappe.conf.get("ceto_jwt_secret"):
		return secret

	# Derive a purpose-specific signing key from Frappe's per-site encryption key
	# so the same key material is not used directly for encryption and JWTs.
	from frappe.utils.password import get_encryption_key

	return _derive_jwt_secret(get_encryption_key())


def _derive_jwt_secret(encryption_key: str) -> str:
	"""Derive a 256-bit JWT key with HKDF-SHA256."""
	pseudorandom_key = hmac.digest(_HKDF_SALT, encryption_key.encode(), hashlib.sha256)
	return hmac.digest(pseudorandom_key, _HKDF_INFO + b"\x01", hashlib.sha256).hex()


def _token_expiry_seconds(purpose: str = AUTH_PURPOSE) -> int:
	if purpose == PASSWORD_RESET_PURPOSE:
		default = DEFAULT_PASSWORD_RESET_EXPIRY_SECONDS
		setting = "ceto_password_reset_token_expiry_seconds"
	elif purpose == REGISTRATION_PURPOSE:
		default = DEFAULT_REGISTRATION_EXPIRY_SECONDS
		setting = "ceto_registration_token_expiry_seconds"
	else:
		default = DEFAULT_TOKEN_EXPIRY_SECONDS
		setting = "ceto_jwt_expiry_seconds"
	expiry = cint(frappe.conf.get(setting))
	return expiry if expiry > 0 else default


def get_bearer_password_reset_user() -> str:
	"""Resolve the customer identified by the request's password-reset bearer token."""
	token = _get_bearer_token()
	if not token:
		raise frappe.AuthenticationError
	try:
		claims = decode_customer_token(token, purpose=PASSWORD_RESET_PURPOSE)
	except jwt.InvalidTokenError:
		raise frappe.AuthenticationError from None
	return _validate_website_customer(claims["sub"])


def _get_bearer_token() -> str | None:
	authorization = frappe.get_request_header("Authorization", "")
	parts = authorization.split(" ", 1)
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return None
	token = parts[1].strip()
	return token if token.count(".") == 2 else None


def _validate_website_customer(user: str) -> str:
	user_details = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise frappe.AuthenticationError
	return user
