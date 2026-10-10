"""Store product category projections over the published ERPNext Item Group tree.

Categories are the ERPNext ``Item Group`` NestedSet tree, published only
inside the configured storefront roots (Recorded Decision 1): a node is
servable exactly when it is a configured root or descends from one, parsed
once through :mod:`ceto.config.catalog` — nothing outside the roots (the
``All Item Groups`` default tree included) is ever visible, and an unknown
or unpublished id masks as ``404`` like everywhere else on the Store
surface. The page is the tree's own order — ``lft`` ascending, the NestedSet
pre-order walk, with the node name breaking ties (Recorded Decision 6) —
and the count runs over the whole published set before pagination. The
projection is flat (Recorded Decision 5): ``parent_category_id`` names the
published ``parent_item_group`` when the parent is itself published, while
the embedded ``parent_category`` / ``category_children`` stay empty and the
tree expansion flags stay refused query keys. ``rank`` stays ``None`` — no
sibling-ranking source exists — and the timestamps are the real record
``creation`` / ``modified`` (Recorded Decision 8), never fabricated.

The public ``id`` is derived, not stored: ``pcat_`` + a SHA-256 truncation
of the ``Item Group`` node name, so the id is stable and addressable with no
core schema change. The ``handle`` is the slug of ``item_group_name`` — the
node's stable public URL segment.
"""

import hashlib
import re
from typing import Any

import frappe
from frappe.utils.nestedset import get_descendants_of

from ceto.config.catalog import catalog_settings, category_roots
from ceto.routing.exceptions import RouteNotFoundError
from ceto.types.http.store.product_categories import (
	PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT,
	PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET,
	PRODUCT_CATEGORY_LIST_MAX_LIMIT,
	StoreProductCategory,
	StoreProductCategoryListResponse,
	StoreProductCategoryResponse,
)

ITEM_GROUP_FIELDS = (
	"name",
	"item_group_name",
	"parent_item_group",
	"creation",
	"modified",
)

_SLUG_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")


def category_public_id(item_group: str) -> str:
	"""Return the node's stable public id: ``pcat_`` + 128 bits of its name's SHA-256."""
	return "pcat_" + hashlib.sha256(item_group.encode("utf-8")).hexdigest()[:32]


def category_handle(item_group_name: str) -> str:
	"""Slug the Item Group name into its stable public URL segment.

	A name that slugs to nothing (symbols only) falls back to itself, so the
	derived handle is never empty.
	"""
	name = (item_group_name or "").strip()
	slug = _SLUG_SEPARATOR_RE.sub("-", name.lower()).strip("-")
	return slug or name


class ProductCategoryDirectory:
	"""Project the published Item Group subtree onto the pinned Store contract."""

	def list(
		self,
		*,
		limit: int = PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT,
		offset: int = PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET,
	) -> StoreProductCategoryListResponse:
		"""Return the pinned ``{product_categories, count, offset, limit}`` envelope."""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), PRODUCT_CATEGORY_LIST_MAX_LIMIT)
		categories = self.published()
		return StoreProductCategoryListResponse(
			product_categories=categories[offset : offset + limit],
			count=len(categories),
			offset=offset,
			limit=limit,
		)

	def get(self, category_id: str) -> StoreProductCategoryResponse:
		"""Return one published category by its public id; unknown or unpublished masks as 404."""
		by_id = {category.id: category for category in self.published()}
		category = by_id.get(category_id)
		if category is None:
			raise RouteNotFoundError(f"Product category {category_id or '(not set)'} not found")
		return StoreProductCategoryResponse(product_category=category)

	def published(self) -> list[StoreProductCategory]:
		"""Return every published category in ``lft`` order — the servable set.

		The configured roots resolve through ``ceto.config.catalog``; an
		unknown root publishes nothing instead of failing the read. Store
		reads dispatch as Guest, so the tree walk reads Item Groups
		permission-free exactly like the row fetch itself.
		"""
		roots = category_roots(catalog_settings())
		if not roots:
			return []
		names = set()
		for root in frappe.get_all("Item Group", filters={"name": ("in", list(roots))}, pluck="name"):
			names.add(root)
			names.update(get_descendants_of("Item Group", root, order_by="lft", ignore_permissions=True))
		if not names:
			return []
		rows = frappe.get_all(
			"Item Group",
			filters={"name": ("in", sorted(names))},
			fields=ITEM_GROUP_FIELDS,
			order_by="lft asc, name asc",
		)
		published_names = {row.name for row in rows}
		return [self._projection(row, published_names) for row in rows]

	@staticmethod
	def _projection(row: Any, published_names: set[str]) -> StoreProductCategory:
		"""Project one published node onto the pinned flat entity."""
		return StoreProductCategory(
			id=category_public_id(row.name),
			name=row.item_group_name,
			handle=category_handle(row.item_group_name),
			parent_category_id=(
				category_public_id(row.parent_item_group)
				if row.parent_item_group in published_names
				else None
			),
			created_at=row.creation,
			updated_at=row.modified,
		)
