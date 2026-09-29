"""Public variant id → ERPNext Item code resolution for cart line items.

Phase 2 treats the Medusa ``variant_id`` as the ERPNext Item code directly
(the field mapping allows ``item_code`` resolution at add time). Resolution is
isolated in this module so a future variant provider (catalog indirection,
per-channel item codes, ...) can replace it without touching cart services.
"""

import frappe

from ceto.routing.exceptions import InvalidDataError


def resolve_item_code(variant_id: str) -> str:
	"""Return the ERPNext Item code for a public ``variant_id``."""
	if not frappe.db.exists("Item", {"name": variant_id, "disabled": 0}):
		raise InvalidDataError(f"Unknown variant id: {variant_id}")
	return variant_id
