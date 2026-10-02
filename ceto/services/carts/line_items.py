"""Line-item domain service for Ceto carts.

Owns everything below cart orchestration: stable ``li_`` identities, the
``Ceto Cart Line Item Reference`` mapping between the public line id and the
real Quotation Item child-row ``name``, row add/update/delete and per-line
metadata persistence. All rates, discounts and taxes are produced by ERPNext
controllers; nothing in this module derives totals.
"""

import json
import secrets
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.variants import resolve_item_code
from ceto.types.http.store.carts import StoreAddCartLineItem, StoreUpdateCartLineItem

if TYPE_CHECKING:
	from frappe.model.document import Document

LINE_NOT_FOUND = "Line item not found"

# ERPNext summary fields that describe an empty cart. ``calculate_taxes_and_totals``
# returns early for itemless documents, so these are reset to the empty-cart
# baseline instead of being recomputed; no total is derived here.
EMPTY_CART_TOTAL_FIELDS = (
	"total_qty",
	"total",
	"base_total",
	"net_total",
	"base_net_total",
	"total_taxes_and_charges",
	"base_total_taxes_and_charges",
	"grand_total",
	"base_grand_total",
	"rounded_total",
	"base_rounded_total",
	"discount_amount",
	"base_discount_amount",
)


class CartLineItems:
	"""Domain operations on cart lines mapped to Quotation Item rows."""

	@staticmethod
	def new_line_id() -> str:
		"""Return a stable public line id: ``li_`` + 128 bits of crypto random."""
		return f"li_{secrets.token_hex(16)}"

	@classmethod
	def add(
		cls,
		reference: "Document",
		quotation: "Document",
		payload: StoreAddCartLineItem,
	) -> "Document":
		"""Append one Quotation Item row and map it to a fresh line id.

		Adding a variant that is already on the cart merges quantities into the
		existing row (Medusa's default add behaviour); the existing line keeps
		its identity and metadata.
		"""
		item_code = resolve_item_code(payload.variant_id)
		existing_row = cls._row_for_item(quotation, item_code)
		is_new_line = existing_row is None
		if is_new_line:
			quotation.append("items", {"item_code": item_code, "qty": payload.quantity})
		else:
			existing_row.qty = flt(existing_row.qty) + payload.quantity
		cls.save(quotation)
		if is_new_line:
			return cls._create_mapping(reference, quotation, payload)
		# Merged add: quantities moved onto the existing line.
		return cls._existing_mapping(quotation)

	@staticmethod
	def _existing_mapping(quotation: "Document") -> "Document":
		"""Return the mapping of the (already-mapped) last Quotation Item row."""
		mapping = frappe.db.get_value(
			"Ceto Cart Line Item Reference",
			{"quotation": quotation.name, "quotation_item": quotation.items[-1].name},
			"name",
		)
		return frappe.get_doc("Ceto Cart Line Item Reference", mapping)

	@classmethod
	def _create_mapping(
		cls,
		reference: "Document",
		quotation: "Document",
		payload: StoreAddCartLineItem,
	) -> "Document":
		"""Create and insert the mapping for the last, freshly appended row."""
		return frappe.get_doc(
			{
				"doctype": "Ceto Cart Line Item Reference",
				"line_id": cls.new_line_id(),
				"cart_reference": reference.name,
				"quotation": quotation.name,
				"quotation_item": quotation.items[-1].name,
				"metadata": dump_metadata(payload.metadata),
			}
		).insert(ignore_permissions=True)

	@classmethod
	def update(
		cls,
		reference: "Document",
		quotation: "Document",
		line_id: str,
		payload: StoreUpdateCartLineItem,
	) -> "Document":
		"""Update quantity and/or metadata of a mapped line in place."""
		mapping = cls.resolve(reference.name, line_id)
		row = cls._row(quotation, mapping.quotation_item)
		fields = payload.model_fields_set
		if "quantity" in fields:
			row.qty = payload.quantity
		if "metadata" in fields:
			mapping.metadata = merged_metadata(mapping.metadata, payload.metadata)
		cls.save(quotation)
		mapping.save(ignore_permissions=True)
		return mapping

	@classmethod
	def delete(
		cls,
		reference: "Document",
		quotation: "Document",
		line_id: str,
	) -> "Document":
		"""Remove a mapped Quotation Item row and its line reference."""
		mapping = cls.resolve(reference.name, line_id)
		row = cls._row(quotation, mapping.quotation_item)
		quotation.remove(row)
		cls.save(quotation)
		frappe.delete_doc("Ceto Cart Line Item Reference", mapping.name, ignore_permissions=True)
		return mapping

	@staticmethod
	def save(quotation: "Document") -> None:
		"""Persist the Quotation through ERPNext controllers.

		Empty carts stay valid, so the mandatory items check is only relaxed
		when no rows remain; ERPNext skips ``calculate_taxes_and_totals`` for
		itemless documents, so the empty cart gets its baseline totals reset.
		"""
		if not quotation.items:
			for field in EMPTY_CART_TOTAL_FIELDS:
				setattr(quotation, field, 0)
			for tax in quotation.get("taxes", []):
				tax.tax_amount = 0
				tax.base_tax_amount = 0
		quotation.flags.ignore_mandatory = not quotation.items
		quotation.save(ignore_permissions=True)

	@staticmethod
	def _row_for_item(quotation: "Document", item_code: str) -> "Document | None":
		for row in quotation.items:
			if row.item_code == item_code:
				return row
		return None

	@staticmethod
	def resolve(cart_reference: str, line_id: str) -> "Document":
		"""Return the mapping for ``line_id``, 404-masked for unknown/foreign ids."""
		try:
			mapping = frappe.get_doc("Ceto Cart Line Item Reference", line_id)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError(LINE_NOT_FOUND)
		if mapping.cart_reference != cart_reference:
			raise RouteNotFoundError(LINE_NOT_FOUND)
		return mapping

	@staticmethod
	def _row(quotation: "Document", quotation_item: str) -> "Document":
		"""Find a child row on the locked/reloaded Quotation, 404-masked."""
		for row in quotation.items:
			if row.name == quotation_item:
				return row
		raise RouteNotFoundError(LINE_NOT_FOUND)


def dump_metadata(metadata: dict[str, Any] | None) -> str | None:
	"""Serialize metadata for storage on a reference record."""
	return json.dumps(metadata, separators=(",", ":"), sort_keys=True) if metadata else None


def merged_metadata(current: str | None, update: dict[str, Any] | None) -> str | None:
	"""Merge cart/line metadata: null values remove keys, ``None`` clears all."""
	if update is None:
		return None
	metadata = json.loads(current) if current else {}
	for key, value in update.items():
		if value is None:
			metadata.pop(key, None)
		else:
			metadata[key] = value
	return dump_metadata(metadata)
