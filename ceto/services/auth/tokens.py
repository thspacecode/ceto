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
_HKDF_SALT = b"ceto-jwt-hkdf-sha256-v1"
_HKDF_INFO = b"ceto/customer-token/hs256"


def create_customer_token(user: str) -> str:
	"""Create the bearer token returned by the Medusa-compatible auth endpoint."""
	now = datetime.now(UTC)
	return jwt.encode(
		{
			"sub": user,
			"actor_type": "customer",
			"iss": ISSUER,
			"iat": now,
			"exp": now + timedelta(seconds=_token_expiry_seconds()),
			"jti": uuid.uuid4().hex,
		},
		_jwt_secret(),
		algorithm=ALGORITHM,
	)


def refresh_customer_token(user: str) -> str:
	"""Issue a new token only for an enabled website customer."""
	user_details = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise frappe.AuthenticationError
	return create_customer_token(user)


def decode_customer_token(token: str) -> dict:
	"""Validate a Ceto customer token and return its claims."""
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

	authorization = frappe.get_request_header("Authorization", "")
	parts = authorization.split(" ", 1)
	if len(parts) != 2 or parts[0].lower() != "bearer":
		return

	token = parts[1].strip()
	# OAuth access tokens are also Bearer tokens. Only claim JWT-shaped values;
	# otherwise let Frappe's other authentication handlers process the request.
	if token.count(".") != 2:
		return

	try:
		claims = decode_customer_token(token)
	except jwt.InvalidTokenError:
		raise frappe.AuthenticationError

	user = claims["sub"]
	user_details = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise frappe.AuthenticationError

	# The signed token's subject is accepted only after issuer, actor type, expiry,
	# enabled state, and Website User type validation above.
	frappe.set_user(user)  # nosemgrep: frappe-setuser


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


def _token_expiry_seconds() -> int:
	expiry = cint(frappe.conf.get("ceto_jwt_expiry_seconds"))
	return expiry if expiry > 0 else DEFAULT_TOKEN_EXPIRY_SECONDS
