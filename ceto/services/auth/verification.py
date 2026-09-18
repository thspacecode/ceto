import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import frappe
from frappe.utils import cint

DEFAULT_VERIFICATION_EXPIRY_SECONDS = 15 * 60
DEFAULT_VERIFIED_EXPIRY_SECONDS = 60 * 60
TOKEN_CODE_PROVIDER = "token"
EMAIL_ENTITY_TYPE = "email"


def request_verification(
	*,
	entity_id: str,
	entity_type: str,
	code_provider: str,
	metadata: dict[str, Any] | None = None,
) -> None:
	"""Create a single-use verification code and notify configured subscribers."""
	_validate_provider(code_provider)
	entity_id = entity_id.strip().lower() if entity_type == EMAIL_ENTITY_TYPE else entity_id.strip()
	if not entity_id:
		raise frappe.ValidationError("entity_id must not be empty")

	code = secrets.token_urlsafe(32)
	expires_at = datetime.now(UTC) + timedelta(seconds=_verification_expiry_seconds())
	verification = {
		"entity_id": entity_id,
		"entity_type": entity_type,
		"code_provider": code_provider,
		"metadata": metadata or {},
		"expires_at": expires_at.isoformat(),
	}
	frappe.cache.set_value(
		_verification_key(code),
		verification,
		expires_in_sec=_verification_expiry_seconds(),
	)
	_run_hooks(
		"ceto_auth_verification_requested",
		**verification,
		code=code,
	)


def confirm_verification(*, code: str, code_provider: str = TOKEN_CODE_PROVIDER) -> dict[str, Any]:
	"""Consume a verification code and record its identity as recently verified."""
	_validate_provider(code_provider)
	key = _verification_key(code)
	lock_name = frappe.cache.make_key(f"{key}:consume")
	with frappe.cache.lock(lock_name, timeout=5, blocking_timeout=2):
		verification = frappe.cache.get_value(key, expires=True, use_local_cache=False)
		if not verification or verification.get("code_provider") != code_provider:
			raise frappe.ValidationError("Invalid or expired verification code")
		frappe.cache.delete_value(key)

	verified_key = _verified_key(verification["entity_type"], verification["entity_id"])
	frappe.cache.set_value(
		verified_key,
		verification,
		expires_in_sec=_verified_expiry_seconds(),
	)
	_run_hooks("ceto_auth_verification_confirmed", **verification)
	return verification


def is_verified(entity_type: str, entity_id: str) -> bool:
	"""Return whether the identity has a recent confirmed verification."""
	if entity_type == EMAIL_ENTITY_TYPE:
		entity_id = entity_id.strip().lower()
	return bool(
		frappe.cache.get_value(
			_verified_key(entity_type, entity_id),
			expires=True,
			use_local_cache=False,
		)
	)


def _validate_provider(code_provider: str) -> None:
	if code_provider != TOKEN_CODE_PROVIDER:
		raise frappe.ValidationError(f"Unsupported verification code provider: {code_provider}")


def _run_hooks(hook: str, **payload: Any) -> None:
	for method in frappe.get_hooks(hook, []):
		frappe.call(frappe.get_attr(method), **payload)


def _verification_key(code: str) -> str:
	digest = hashlib.sha256(code.encode()).hexdigest()
	return f"ceto:auth:verification:{digest}"


def _verified_key(entity_type: str, entity_id: str) -> str:
	digest = hashlib.sha256(f"{entity_type}:{entity_id}".encode()).hexdigest()
	return f"ceto:auth:verified:{digest}"


def _verification_expiry_seconds() -> int:
	expiry = cint(frappe.conf.get("ceto_auth_verification_expiry_seconds"))
	return expiry if expiry > 0 else DEFAULT_VERIFICATION_EXPIRY_SECONDS


def _verified_expiry_seconds() -> int:
	expiry = cint(frappe.conf.get("ceto_auth_verified_expiry_seconds"))
	return expiry if expiry > 0 else DEFAULT_VERIFIED_EXPIRY_SECONDS
