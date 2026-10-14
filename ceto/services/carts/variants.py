"""Public variant id → ERPNext Item code resolution for cart line items.

The Medusa ``variant_id`` is the ERPNext ``Item`` code (the field mapping
allows ``item_code`` resolution at add time). Resolution delegates to the
single publication authority — ``ceto.services.catalog.publication`` — so a
cart can only ever carry what the catalog publishes: enabled sales items
inside the configured storefront roots, a variant of a template family or a
standalone item, never the template itself. The resolved code is always the
exact stored ``Item`` code, and the resolver stays the only cart touchpoint,
so a future variant provider can replace the authority without touching
cart services.
"""

from ceto.routing.exceptions import InvalidDataError
from ceto.services.catalog.publication import published_item_code


def resolve_item_code(variant_id: str) -> str:
	"""Return the exact published, purchasable ERPNext Item code for a ``variant_id``.

	Every refusal — an unknown id, a disabled or non-sales item, a variant
	family's template, an item outside the configured storefront roots — is
	the same ``invalid_data`` error the resolver has always masked unknown
	ids with.
	"""
	item_code = published_item_code(variant_id)
	if item_code is None:
		raise InvalidDataError(f"Unknown variant id: {variant_id}")
	return item_code
