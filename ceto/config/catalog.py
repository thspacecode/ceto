"""Shared parsing of the private ``ceto_catalog`` site configuration.

The category directory (``ceto.services.catalog.product_categories``)
resolves the storefront root ``Item Group`` nodes through this module, so the
served taxonomy cannot drift from the configured one: one config shape, one
parser. Like :mod:`ceto.config.cart`, the module owns only parsing and
lookup; it never validates that the configured roots exist — the directory
applies its own publication rule on top, and an unknown root simply
publishes nothing instead of failing the read.
"""

from typing import Any

import frappe

CATALOG_CONFIG_KEY = "ceto_catalog"


def catalog_settings() -> dict[str, Any]:
	"""Return the raw ``ceto_catalog`` mapping from the site configuration."""
	value = frappe.conf.get(CATALOG_CONFIG_KEY)
	return dict(value) if isinstance(value, dict) else {}


def category_roots(settings: dict[str, Any]) -> tuple[str, ...]:
	"""Return the configured storefront root Item Group names, order kept.

	The ``category_roots`` value may be one name or a list of names; blank
	and non-string entries are dropped and duplicates collapse, never an
	error. An absent or unusable value is an empty tuple — with no
	configuration the directory publishes nothing, the safe default behind
	the routes.
	"""
	value = settings.get("category_roots")
	if isinstance(value, str):
		value = [value]
	if not isinstance(value, (list, tuple)):
		return ()
	names = (name.strip() for name in value if isinstance(name, str))
	return tuple(dict.fromkeys(name for name in names if name))
