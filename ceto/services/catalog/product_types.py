"""Store product type projections over Ceto-owned catalog storage.

Product types are Ceto-curated catalog records (Recorded Decision 3): the
``value`` is the curated label and the record's stable business key, the
``ptyp_…`` id is minted, and no ERPNext master owns them. The directory is
the read-only Store projection: ``value``-ascending order (Recorded
Decision 6) with the record id breaking ties, pages echoing the effective
``offset`` / ``limit`` with the count taken over the whole stored set, the
real record ``creation`` / ``modified`` timestamps served as-is (Recorded
Decision 8), and the optional ``external_id`` / ``metadata`` columns
projected verbatim. An unknown id masks as ``404`` like everywhere else on
the Store surface.
"""

import json
import secrets
from typing import Any

import frappe

from ceto.routing.exceptions import RouteNotFoundError
from ceto.types.http.store.product_types import (
	PRODUCT_TYPE_LIST_DEFAULT_LIMIT,
	PRODUCT_TYPE_LIST_DEFAULT_OFFSET,
	PRODUCT_TYPE_LIST_MAX_LIMIT,
	StoreProductType,
	StoreProductTypeListResponse,
	StoreProductTypeResponse,
)

PRODUCT_TYPE_FIELDS = (
	"type_id",
	"value",
	"external_id",
	"metadata",
	"creation",
	"modified",
)


def new_product_type_id() -> str:
	"""Return a stable public type id: ``ptyp_`` + 128 bits of crypto random."""
	return f"ptyp_{secrets.token_hex(16)}"


class ProductTypeDirectory:
	"""Project the Ceto-stored product types onto the pinned Store contract."""

	def list(
		self,
		*,
		limit: int = PRODUCT_TYPE_LIST_DEFAULT_LIMIT,
		offset: int = PRODUCT_TYPE_LIST_DEFAULT_OFFSET,
	) -> StoreProductTypeListResponse:
		"""Return the pinned ``{product_types, count, offset, limit}`` envelope."""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), PRODUCT_TYPE_LIST_MAX_LIMIT)
		rows = self._rows(offset=offset, limit=limit)
		return StoreProductTypeListResponse(
			product_types=[self._projection(row) for row in rows],
			count=frappe.db.count("Ceto Product Type"),
			offset=offset,
			limit=limit,
		)

	def get(self, type_id: str) -> StoreProductTypeResponse:
		"""Return one stored type by its public id; unknown ids mask as 404."""
		rows = frappe.get_all(
			"Ceto Product Type",
			filters={"type_id": type_id},
			fields=PRODUCT_TYPE_FIELDS,
			limit_page_length=1,
		)
		if not rows:
			raise RouteNotFoundError(f"Product type {type_id or '(not set)'} not found")
		return StoreProductTypeResponse(product_type=self._projection(rows[0]))

	def _rows(self, *, offset: int, limit: int) -> list[Any]:
		"""Load one deterministic page: value ascending, record id breaking ties."""
		if not limit:
			return []
		return frappe.get_all(
			"Ceto Product Type",
			fields=PRODUCT_TYPE_FIELDS,
			order_by="value asc, name asc",
			offset=offset,
			limit_page_length=limit,
		)

	@staticmethod
	def _projection(row: Any) -> StoreProductType:
		"""Project one stored type onto the pinned entity."""
		return StoreProductType(
			id=row.type_id,
			value=row.value,
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
