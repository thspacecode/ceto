"""Pinned ``StoreProductCategory`` entity contract.

Mirrors ``http/product-category/store`` of ``@medusajs/types@2.21.1`` for
the columns Ceto projects from the published ERPNext ``Item Group`` nodes
(``docs/catalog/field-mapping.md``):

- The pinned store type omits ``is_active`` / ``is_internal`` — publication
  is a projection decision (Recorded Decision 1: only ``Item Group`` nodes
  inside the configured storefront roots are served), never a served flag.
- ``description`` stays optional and is left ``None`` on purpose: ERPNext
  ``Item Group`` carries no description, and Ceto never fabricates one.
- ``handle`` derives from the ``Item Group`` name; ``rank`` stays ``None``
  until a ranking source exists (``gap``).
- ``parent_category`` / ``category_children`` mirror the pinned relations
  and default to the empty tree (``None`` / ``[]``): the flat projection
  ships first and the tree population is a behavior-slice decision.
- ``created_at`` / ``updated_at`` are real record timestamps (ERPNext
  ``creation`` / ``modified``) once served — they stay optional in the
  contract like every column, never ``None`` by policy for stored records
  (Recorded Decision 8).
- ``deleted_at`` stays optional and is never populated: ERPNext deletes
  ``Item Group`` nodes hard, there is no soft-delete tombstone.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StoreProductCategory(BaseModel):
	"""Medusa ``StoreProductCategory`` shape (Phase 2 subset)."""

	id: str
	name: str
	handle: str
	description: str | None = None
	rank: int | None = None
	parent_category_id: str | None = None
	parent_category: StoreProductCategory | None = None
	category_children: list[StoreProductCategory] = []
	external_id: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
