"""Throwaway catalog fixtures for the collections / product types suites.

The catalog storage is Ceto-owned, so the taxonomy suites mint their own
records through the same controller path the bootstrap fixtures use. The
factories here keep minted ids, handles and values unique per record, so no
suite depends on table state or run order.
"""

import uuid
from typing import Any

import frappe

from ceto.services.catalog.collections import new_collection_id
from ceto.services.catalog.product_types import new_product_type_id


class CatalogTestData:
	"""Mint disposable collections and product types for one test."""

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
