"""The single publication authority for the storefront catalog.

One rule decides what the Store surface may serve: an ERPNext ``Item`` is
published exactly when it is enabled, is a sales item, and its ``Item
Group`` sits inside the configured storefront roots — the roots plus every
NestedSet descendant, resolved through :mod:`ceto.config.catalog`
(catalog field-mapping Recorded Decision 1). Every consumer — the category
directory's published tree, the cart's variant resolver, the products
behavior slice to come — asks this module instead of re-deriving the
boundary, so the served assortment can never drift from the one deployment
decision.

The template/variant/standalone semantics are fixed here too: a template
(``has_variants``) is a variant family's head, never a sellable unit — only
its variants resolve — while a variant (``variant_of`` set) and a
standalone item (neither) are published alike once the base rules pass.
Publication is a projection decision: nothing is written to ERPNext, no
core field is added, and with no roots configured nothing is published —
the safe default behind every route.
"""

from typing import Any

import frappe
from frappe.utils.nestedset import get_descendants_of

from ceto.config.catalog import catalog_settings, category_roots

ITEM_PUBLICATION_FIELDS = (
	"name",
	"disabled",
	"is_sales_item",
	"has_variants",
	"variant_of",
	"item_group",
)


def published_item_group_names() -> set[str]:
	"""Return the configured storefront roots plus every NestedSet descendant.

	Roots resolve through ``ceto.config.catalog``; each existing root
	contributes its ``Item Group`` subtree, and an unknown root contributes
	nothing instead of failing the read. With no usable configuration the
	set is empty — nothing is published.
	"""
	roots = category_roots(catalog_settings())
	names: set[str] = set()
	for root in frappe.get_all("Item Group", filters={"name": ("in", list(roots))}, pluck="name"):
		names.add(root)
		names.update(get_descendants_of("Item Group", root, order_by="lft", ignore_permissions=True))
	return names


def published_item_code(variant_id: str) -> str | None:
	"""Resolve a presented variant id to the published sellable ``Item`` code, or ``None``.

	The lookup names the ``Item`` row; the returned code is always the
	stored ``Item`` code — the exact ERPNext identity that carts and
	serialization must carry. ``None`` means unpublished: missing, disabled,
	a non-sales item, a variant family's template, or an ``Item Group``
	outside the configured storefront roots.
	"""
	row = frappe.db.get_value("Item", {"name": variant_id}, ITEM_PUBLICATION_FIELDS, as_dict=True)
	if row is None or not _sellable(row):
		return None
	return row.name


def is_item_published(item_code: str) -> bool:
	"""Whether the exact ERPNext ``Item`` code is a published sellable unit.

	The authority addresses items by their exact stored code only: a
	presentation that differs in case resolves through
	:func:`published_item_code`, but it is not this exact code and so does
	not count as published.
	"""
	return published_item_code(item_code) == item_code


def _sellable(row: Any) -> bool:
	"""Apply the publication rules to one fetched ``Item`` row."""
	if int(row.disabled) or not int(row.is_sales_item) or int(row.has_variants):
		return False
	return row.item_group in published_item_group_names()
