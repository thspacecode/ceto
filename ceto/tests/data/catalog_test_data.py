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
	"""Mint disposable collections, product types, Item Groups and Items for one test."""

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

	def item_attribute(self, *values: str, name: str | None = None) -> str:
		"""Mint one throwaway Item Attribute master with the given allowed values.

		``name`` pins the master's name instead of minting one — the golden
		fixture suites pin the attribute into derived option titles and ids,
		so their assortment must name it deterministically. Fixed names are
		safe the way fixed Item Group names are: the per-test rollback
		removes the master again.
		"""
		name = name or f"Dev Colour {uuid.uuid4().hex[:8]}"
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": name,
				"numeric_values": 0,
				"item_attribute_values": [
					{"attribute_value": value or "Black", "abbr": (value or "Black")[:3].upper()}
					for value in (values or ("Black",))
				],
			}
		).insert(ignore_permissions=True)
		return name

	def template_item(self, *, item_code: str | None = None, **overrides: Any):
		"""Mint one throwaway variant-family template Item for one test."""
		suffix = uuid.uuid4().hex[:12].upper()
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code or f"DEV-TMPL-{suffix}",
				"item_name": f"Dev Template Item {suffix}",
				"item_group": "All Item Groups",
				"stock_uom": "Unit",
				"has_variants": 1,
				"attributes": [{"attribute": self.item_attribute()}],
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def variant_item(
		self, template: Any, *, attribute_value: str = "Black", item_code: str | None = None, **overrides: Any
	):
		"""Mint one sellable variant of ``template`` with a valid attribute value."""
		suffix = uuid.uuid4().hex[:12].upper()
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code or f"DEV-VAR-{suffix}",
				"item_name": f"Dev Variant Item {suffix}",
				"item_group": template.item_group,
				"stock_uom": "Unit",
				"variant_of": template.name,
				"attributes": [
					{"attribute": template.attributes[0].attribute, "attribute_value": attribute_value}
				],
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def item_price(
		self,
		item: Any,
		rate: float | str,
		*,
		price_list: str,
		uom: str | None = None,
		valid_from: str | None = None,
		valid_upto: str | None = None,
		**overrides: Any,
	):
		"""Seed one throwaway selling Item Price row for an item.

		``valid_from`` pins the bootstrap convention so the row's identity is
		stable instead of defaulting to Today during insert.
		"""
		item_code = item if isinstance(item, str) else item.name
		doc = frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item_code,
				"price_list": price_list,
				"uom": uom,
				"price_list_rate": rate,
				"valid_from": valid_from or "2000-01-01",
				"valid_upto": valid_upto,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def barcode(self, item: Any, barcode: str | None = None, *, barcode_type: str | None = None) -> str:
		"""Attach one barcode row to an Item and return the exact value."""
		value = barcode or f"DEV-{uuid.uuid4().hex[:12]}"
		doc = item if not isinstance(item, str) else frappe.get_doc("Item", item)
		doc.append("barcodes", {"barcode": value, "barcode_type": barcode_type})
		doc.save(ignore_permissions=True)
		return value

	def merchandising(self, item: Any, *, collection: Any = None, product_type: Any = None):
		"""Link an Item to a stored collection and/or product type."""
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Product Merchandising",
				"item": item if isinstance(item, str) else item.name,
				"collection": collection.collection_id if collection else None,
				"product_type": product_type.type_id if product_type else None,
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
