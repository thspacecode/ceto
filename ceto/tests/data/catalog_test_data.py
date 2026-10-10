"""Throwaway catalog fixtures for the catalog taxonomy suites.

The catalog storage is Ceto-owned, so the taxonomy suites mint their own
records through the same controller paths the bootstrap fixtures use —
including throwaway ``Item Group`` nodes, which the category suites publish
through the storefront-roots site configuration, and throwaway ``Item`` tag
links, which the tag suites pin through the exact live ``Tag Link`` rows.
The factories here keep minted ids, handles and values unique per record, so
no suite depends on table state or run order.
"""

import uuid
from typing import Any

import frappe

from ceto.services.catalog.collections import new_collection_id
from ceto.services.catalog.product_tags import ensure_tag_master
from ceto.services.catalog.product_types import new_product_type_id


class CatalogTestData:
	"""Mint disposable collections, product types and Item Groups for one test."""

	def collection(self, *, title: str = "Dev Collection", handle: str | None = None, **overrides: Any):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Collection",
				"collection_id": new_collection_id(),
				"title": title,
				"handle": handle or f"dev-{uuid.uuid4().hex[:12]}",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def product_type(self, *, value: str | None = None, **overrides: Any):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Product Type",
				"type_id": new_product_type_id(),
				"value": value or f"Dev Type {uuid.uuid4().hex[:8]}",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def item_group(self, name: str, *, parent: str = "All Item Groups", is_group: bool = False):
		"""Mint (or reuse) one throwaway Item Group node for one test.

		The per-test transaction rollback removes the node again, so the
		fixed demo names stay readable without ever colliding with the
		committed baseline.
		"""
		if frappe.db.exists("Item Group", name):
			return frappe.get_doc("Item Group", name)
		doc = frappe.new_doc("Item Group")
		doc.item_group_name = name
		doc.parent_item_group = parent
		doc.is_group = is_group
		doc.insert(ignore_permissions=True)
		return doc

	def item(self, *, item_code: str | None = None, **overrides: Any):
		"""Mint one throwaway sellable Item for one test."""
		suffix = uuid.uuid4().hex[:12].upper()
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code or f"DEV-TAG-{suffix}",
				"item_name": f"Dev Tagged Item {suffix}",
				"item_group": "All Item Groups",
				"stock_uom": "Unit",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def item_tag(self, item: Any, value: str | None = None) -> str:
		"""Attach one live tag to an Item: master plus exact Tag Link row.

		Returns the tag value; the per-test rollback removes the master and
		the link again, so no fixture value ever reaches another test.
		"""
		value = value or f"Dev Tag {uuid.uuid4().hex[:8]}"
		item_name = item if isinstance(item, str) else item.name
		ensure_tag_master(value)
		frappe.get_doc(
			{
				"doctype": "Tag Link",
				"document_type": "Item",
				"document_name": item_name,
				"title": frappe.db.get_value("Item", item_name, "item_name") or "",
				"tag": value,
			}
		).insert(ignore_permissions=True)
		return value

	def orphan_tag_link(self, value: str | None = None) -> str:
		"""Attach one tag to a throwaway Item, then hard-delete the Item row.

		The Desk delete path cleans a document's Tag Link rows; deleting the
		row directly leaves the drifted orphan the served boundary must
		exclude — a live Tag Link naming an Item that no longer exists.
		"""
		value = value or f"Dev Orphan Tag {uuid.uuid4().hex[:8]}"
		item = self.item()
		self.item_tag(item, value)
		frappe.db.delete("Item", item.name)
		return value
