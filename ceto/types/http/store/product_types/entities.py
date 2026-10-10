"""Pinned ``StoreProductType`` entity contract.

Mirrors ``http/product-type/store`` of ``@medusajs/types@2.21.1`` for the
columns Ceto's curated product types project
(``docs/catalog/field-mapping.md``):

- Types are Ceto-curated catalog records with minted ids (Recorded
  Decision 3); ``value`` is the curated label and the only required column
  beyond ``id``.
- ``created_at`` / ``updated_at`` stay optional in the contract: the pinned
  store list serves a field-selected subset without them, so Ceto keeps
  every column optional while the storage slice serves the stored record's
  real timestamps (Recorded Decision 8).
- ``deleted_at`` stays optional and is never populated: the Ceto catalog
  layer deletes hard, there is no soft-delete tombstone.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StoreProductType(BaseModel):
	"""Medusa ``StoreProductType`` shape (Phase 2 subset)."""

	id: str
	value: str
	external_id: str | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
