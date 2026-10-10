"""Store product tag projections over the live Frappe tag masters.

Tags are not Ceto-stored records: the directory projects the live ``Tag``
masters that carry exact live ``Tag Link`` rows for ``Item`` documents
(``docs/catalog/field-mapping.md``). A tag is served exactly when its master
exists and at least one of its Tag Link rows names an ``Item`` that still
exists — orphaned links and links to deleted Items never surface, and a
master without any live link is invisible. The directory is the read-only
Store projection: ``value``-ascending order (Recorded Decision 6), pages
echoing the effective ``offset`` / ``limit`` with the count taken over the
whole served set before pagination, and no timestamps of its own — a tag is
a projection of other records' tags, so ``created_at`` / ``updated_at`` stay
absent, never fabricated (Recorded Decision 8). An unknown id masks as
``404`` like everywhere else on the Store surface.

The public ``id`` is derived, not stored: ``ptag_`` + a SHA-256 truncation
of the tag value, so the id is stable and addressable with no core schema
change — the same derivation pattern the published ``pcat_…`` ids use.
"""

import hashlib

import frappe
from frappe.desk.doctype.tag.tag import DocTags
from frappe.query_builder import Order

from ceto.routing.exceptions import RouteNotFoundError
from ceto.types.http.store.product_tags import (
	PRODUCT_TAG_LIST_DEFAULT_LIMIT,
	PRODUCT_TAG_LIST_DEFAULT_OFFSET,
	PRODUCT_TAG_LIST_MAX_LIMIT,
	StoreProductTag,
	StoreProductTagListResponse,
	StoreProductTagResponse,
)


def tag_public_id(value: str) -> str:
	"""Return the tag's stable public id: ``ptag_`` + 128 bits of its value's SHA-256."""
	return "ptag_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def tag_exists(value: str) -> bool:
	"""Return whether the tag master exists."""
	return bool(frappe.db.exists("Tag", value))


def ensure_tag_master(value: str) -> None:
	"""Create the tag master when missing, mirroring the desk tag editor."""
	if not tag_exists(value):
		frappe.get_doc({"doctype": "Tag", "name": value}).insert(ignore_permissions=True)


def add_item_tag(item_name: str, value: str) -> None:
	"""Attach one live tag to an ``Item``: the Tag Link row is the owned record.

	The desk path (``DocTags``) keeps the denormalized ``_user_tags`` column
	and the Tag Link rows in sync; when the column drifted ahead of the link
	row, the missing link is inserted directly so the served surface always
	converges.
	"""
	DocTags("Item").add(item_name, value)
	if not frappe.db.exists("Tag Link", {"document_type": "Item", "document_name": item_name, "tag": value}):
		frappe.get_doc(
			{
				"doctype": "Tag Link",
				"document_type": "Item",
				"document_name": item_name,
				"title": frappe.db.get_value("Item", item_name, "item_name") or "",
				"tag": value,
			}
		).insert(ignore_permissions=True)


def item_tag_exists(item_name: str, value: str) -> bool:
	"""Return whether the exact live Tag Link row names this ``Item``."""
	return bool(
		frappe.db.exists("Tag Link", {"document_type": "Item", "document_name": item_name, "tag": value})
	)


class ProductTagDirectory:
	"""Project the live Frappe tags onto the pinned Store contract."""

	def list(
		self,
		*,
		limit: int = PRODUCT_TAG_LIST_DEFAULT_LIMIT,
		offset: int = PRODUCT_TAG_LIST_DEFAULT_OFFSET,
	) -> StoreProductTagListResponse:
		"""Return the pinned ``{product_tags, count, offset, limit}`` envelope."""
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), PRODUCT_TAG_LIST_MAX_LIMIT)
		values = self.served_values()
		return StoreProductTagListResponse(
			product_tags=[self._projection(value) for value in values[offset : offset + limit]],
			count=len(values),
			offset=offset,
			limit=limit,
		)

	def get(self, tag_id: str) -> StoreProductTagResponse:
		"""Return one served tag by its public id; unknown ids mask as 404."""
		by_id = {tag.id: tag for tag in self.served()}
		tag = by_id.get(tag_id)
		if tag is None:
			raise RouteNotFoundError(f"Product tag {tag_id or '(not set)'} not found")
		return StoreProductTagResponse(product_tag=tag)

	def served(self) -> list[StoreProductTag]:
		"""Return every served tag in value order — the servable set."""
		return [self._projection(value) for value in self.served_values()]

	def served_values(self) -> list[str]:
		"""Return every served tag value, value-ascending.

		An exact live ``Tag Link`` row serves only while the tagged ``Item``
		still exists and the referenced ``Tag`` master is still live; the
		distinct surviving values are the served set.
		"""
		tag = frappe.qb.DocType("Tag")
		link = frappe.qb.DocType("Tag Link")
		item = frappe.qb.DocType("Item")
		return (
			frappe.qb.from_(tag)
			.inner_join(link)
			.on(link.tag == tag.name)
			.inner_join(item)
			.on(item.name == link.document_name)
			.where(link.document_type == "Item")
			.select(tag.name.as_("value"))
			.distinct()
			.orderby(tag.name, order=Order.asc)
			.run(pluck=True)
		)

	@staticmethod
	def _projection(value: str) -> StoreProductTag:
		"""Project one served tag onto the pinned entity."""
		return StoreProductTag(
			id=tag_public_id(value),
			value=value,
		)
