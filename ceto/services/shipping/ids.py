"""Reversible public shipping-option ids.

The pinned shipping-option contract serves option ids as opaque, stable
tokens ``so_<base64url(provider_id + ':' + option_key)>`` — never the raw
``Shipping Rule`` name; the legacy raw names stay accepted only by the
existing cart apply surface. The encoding is URL-safe base64 without
padding (the pinned token shape ``so_[A-Za-z0-9_-]+``) and it is
reversible: decoding recovers the provider id and the provider's own
option key, so the registry routes a public id to the provider that
minted it without any lookup table.

The separator lives inside the encoded payload, which is why the provider
id may never contain ``:`` — the option key may contain anything, since
the split takes the first separator and keys keep theirs.
"""

import base64
import re

from ceto.services.shipping.errors import MalformedShippingOptionIdError, ShippingOptionError

OPTION_ID_PREFIX = "so_"
OPTION_ID_SEPARATOR = ":"

#: The URL-safe base64 alphabet without padding — the token shape the
#: pinned entity contract allows.
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


def encode_option_id(provider_id: str, option_key: str) -> str:
	"""Return the public ``so_`` token of ``provider_id`` + ``option_key``."""
	_require_identity_part(provider_id, "provider id")
	_require_identity_part(option_key, "option key")
	if OPTION_ID_SEPARATOR in provider_id:
		raise ShippingOptionError(f"A provider id cannot contain {OPTION_ID_SEPARATOR!r}")
	payload = f"{provider_id}{OPTION_ID_SEPARATOR}{option_key}".encode()
	token = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
	return f"{OPTION_ID_PREFIX}{token}"


def decode_option_id(option_id: str) -> tuple[str, str]:
	"""Return ``(provider_id, option_key)`` for a public option id.

	Raises :class:`MalformedShippingOptionIdError` for anything this module
	could not have minted — a wrong prefix, foreign characters, broken
	base64, a missing separator or an empty identity part.
	"""
	if not isinstance(option_id, str) or not option_id.startswith(OPTION_ID_PREFIX):
		raise MalformedShippingOptionIdError(
			f"Shipping option {option_id!r} is not a {OPTION_ID_PREFIX} token"
		)
	token = option_id[len(OPTION_ID_PREFIX) :]
	if not token or not _TOKEN_PATTERN.fullmatch(token):
		raise MalformedShippingOptionIdError(
			f"Shipping option {option_id!r} is not a {OPTION_ID_PREFIX} token"
		)
	try:
		encoded = token + "=" * (-len(token) % 4)
		payload = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
	except ValueError as exc:
		# binascii.Error (broken base64) and UnicodeDecodeError subclass ValueError
		raise MalformedShippingOptionIdError(f"Shipping option {option_id!r} does not decode") from exc
	provider_id, separator, option_key = payload.partition(OPTION_ID_SEPARATOR)
	if not separator or not provider_id or not option_key:
		raise MalformedShippingOptionIdError(f"Shipping option {option_id!r} does not decode")
	return provider_id, option_key


def _require_identity_part(value: object, label: str) -> None:
	if not isinstance(value, str) or not value.strip():
		raise ShippingOptionError(f"A shipping option {label} is required")
