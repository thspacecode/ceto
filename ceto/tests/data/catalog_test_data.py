"""Throwaway catalog fixtures for the catalog taxonomy suites.

The catalog storage is Ceto-owned, so the taxonomy suites mint their own
records through the same controller paths the bootstrap fixtures use —
including throwaway ``Item Group`` nodes, which the category suites publish
through the storefront-roots site configuration. The factories here keep
minted ids, handles and values unique per record, so no suite depends on
table state or run order.
"""

import uuid
from typing import Any

import frappe

from ceto.services.catalog.collections import new_collection_id
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
