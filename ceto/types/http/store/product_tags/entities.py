"""Pinned ``StoreProductTag`` entity contract.

Mirrors ``http/product-tag/store`` of ``@medusajs/types@2.21.1`` for the
columns Ceto projects from the published catalog's tags
(``docs/catalog/field-mapping.md``):

- ``value`` projects the deduplicated Frappe user tags of the published
  catalog items — the only required column beyond ``id``.
- ``id`` is a stable public tag id; minting is decided with the tags
  behavior slice (Recorded Decision 6).
- ``created_at`` / ``updated_at`` stay optional in the contract: the pinned
  store list serves a field-selected subset without them, and a tag is a
  projection of other records' tags — Ceto never fabricates a timestamp for
  it (Recorded Decision 8).
- ``deleted_at`` stays optional and is never populated: tags disappear with
  the last reference, there is no soft-delete tombstone.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StoreProductTag(BaseModel):
	"""Medusa ``StoreProductTag`` shape (Phase 2 subset)."""

	id: str
	value: str
	external_id: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
