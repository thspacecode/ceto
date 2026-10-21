"""Shared parsing of the private ``ceto_cart`` site configuration.

Every reader of the cart configuration — the cart service
(:class:`ceto.services.carts.configuration.CartConfiguration`) and the
reference-data services (:mod:`ceto.services.reference`) — resolves the
``regions`` / ``sales_channels`` mapping entries through this module, so the
two projections cannot drift: one config shape, one parser. The module owns
only parsing and lookup; it never validates that the referenced masters
exist (each consumer applies its own validity rules on top).
"""

from typing import Any

import frappe

from ceto.routing.exceptions import InvalidDataError

CART_CONFIG_KEY = "ceto_cart"


def cart_settings() -> dict[str, Any]:
	"""Return the raw ``ceto_cart`` mapping from the site configuration."""
	return _as_dict(frappe.conf.get(CART_CONFIG_KEY))


def mapped_settings(
	settings: dict[str, Any], mapping_name: str, key: str | None, label: str
) -> dict[str, Any]:
	"""Return one mapping entry, rejecting unknown keys when the mapping exists.

	An absent mapping disables the keyed lookup entirely (the entry is
	empty); a present mapping must know every requested key.
	"""
	mapping = _as_dict(settings.get(mapping_name))
	if not mapping:
		return {}
	if not key or key not in mapping:
		raise InvalidDataError(f"Unknown cart {label}: {key or '(not set)'}")
	return _as_dict(mapping[key])


def region_entries(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
	"""Return every configured region entry keyed by its region id."""
	return _as_dict(settings.get("regions"))


def default_region_id(settings: dict[str, Any]) -> str | None:
	"""Return the configured default region id, if any."""
	value = settings.get("default_region_id")
	return str(value) if value else None


def _as_dict(value: Any) -> dict[str, Any]:
	return dict(value) if isinstance(value, dict) else {}
