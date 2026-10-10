"""Pinned ``StoreCollection`` entity contract.

Mirrors ``http/collection/store`` of ``@medusajs/types@2.21.1`` for the
columns Ceto's stored collections project (``docs/catalog/field-mapping.md``):

- Collections are Ceto-stored catalog records — unique handles, minted ids
  (Recorded Decision 2); the projection keeps the pinned required trio
  ``id`` / ``title`` / ``handle`` mandatory.
- ``created_at`` / ``updated_at`` stay optional in the contract: the pinned
  store list serves a field-selected subset without them, so Ceto keeps
  every column optional while the storage slice serves the stored record's
  real timestamps (Recorded Decision 8).
- ``deleted_at`` mirrors the pinned nullable column but is never populated:
  the Ceto catalog layer deletes hard, there is no soft-delete tombstone.
- ``products`` is dropped from the projection model entirely: collection-item
  membership is deferred (Recorded Decision 4), and Ceto does not stub a
  product contract that does not exist yet.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StoreCollection(BaseModel):
	"""Medusa ``StoreCollection`` shape (Phase 2 subset)."""

	id: str
	title: str
	handle: str
	metadata: dict[str, Any] | None = None
	external_id: str | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
