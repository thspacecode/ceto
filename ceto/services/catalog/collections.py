"""Store collection projections over Ceto-owned catalog storage.

Collections are Ceto-stored catalog records (Recorded Decision 2): unique
stored handles, minted ``pcol_…`` public ids, no ERPNext master. The
directory is the read-only Store projection: creation-descending order —
the upstream validator's pinned default sort — with the record id breaking
ties, pages echoing the effective ``offset`` / ``limit`` with the count
taken over the whole stored set, the real record ``creation`` / ``modified``
timestamps served as-is (Recorded Decision 8), and the optional
``external_id`` / ``metadata`` columns projected verbatim. An id that is
not stored is the same masked ``404`` as anywhere on the Store surface —
never an error surface that leaks catalog state.
"""

import json
import secrets
from typing import Any

import frappe

from ceto.routing.exceptions import RouteNotFoundError
from ceto.types.http.store.collections import (
	COLLECTION_LIST_DEFAULT_LIMIT,
	COLLECTION_LIST_DEFAULT_OFFSET,
	COLLECTION_LIST_MAX_LIMIT,
	StoreCollection,
	StoreCollectionListResponse,
	StoreCollectionResponse,
)

COLLECTION_FIELDS = (
	"collection_id",
	"title",
	"handle",
	"external_id",
	"metadata",
	"creation",
	"modified",
)


def new_collection_id() -> str:
	"""Return a stable public collection id: ``pcol_`` + 128 bits of crypto random."""
	return f"pcol_{secrets.token_hex(16)}"


class CollectionDirectory:
	"""Project the Ceto-stored collections onto the pinned Store contract."""

	def list(
		self,
		*,
		limit: int = COLLECTION_LIST_DEFAULT_LIMIT,
		offset: int = COLLECTION_LIST_DEFAULT_OFFSET,
	) -> StoreCollectionListResponse:
		"""Return the pinned ``{collections, count, offset, limit}`` envelope."""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), COLLECTION_LIST_MAX_LIMIT)
		rows = self._rows(offset=offset, limit=limit)
		return StoreCollectionListResponse(
			collections=[self._projection(row) for row in rows],
			count=frappe.db.count("Ceto Collection"),
			offset=offset,
			limit=limit,
		)

	def get(self, collection_id: str) -> StoreCollectionResponse:
		"""Return one stored collection by its public id; unknown ids mask as 404."""
		rows = frappe.get_all(
			"Ceto Collection",
			filters={"collection_id": collection_id},
			fields=COLLECTION_FIELDS,
			limit_page_length=1,
		)
		if not rows:
			raise RouteNotFoundError(f"Collection {collection_id or '(not set)'} not found")
		return StoreCollectionResponse(collection=self._projection(rows[0]))

	def _rows(self, *, offset: int, limit: int) -> list[Any]:
		"""Load one deterministic page: creation descending, record id breaking ties."""
		if not limit:
			return []
		return frappe.get_all(
			"Ceto Collection",
			fields=COLLECTION_FIELDS,
			order_by="creation desc, name desc",
			offset=offset,
			limit_page_length=limit,
		)

	@staticmethod
	def _projection(row: Any) -> StoreCollection:
		"""Project one stored collection onto the pinned entity."""
		return StoreCollection(
			id=row.collection_id,
			title=row.title,
			handle=row.handle,
			external_id=row.external_id or None,
			metadata=_parsed_metadata(row.metadata),
			created_at=row.creation,
			updated_at=row.modified,
		)


def _parsed_metadata(stored: str | None) -> dict[str, Any] | None:
	"""Parse the stored canonical JSON object; unreadable payloads project as absent.

	The controller canonicalizes every write, so ``None`` here means unset;
	a value that still fails to parse must never break a public read.
	"""
	if not stored:
		return None
	try:
		parsed = json.loads(stored)
	except ValueError:
		return None
	return parsed if isinstance(parsed, dict) else None
