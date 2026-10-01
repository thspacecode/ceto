import json
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import flt, get_datetime

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.addresses import serialize_address
from ceto.types.http.store.carts import StoreCart, StoreCartLineItem, StoreCartPromotion

if TYPE_CHECKING:
	from frappe.model.document import Document


class CartSerializer:
	def serialize(
		self,
		reference: "Document",
		quotation: "Document",
		*,
		fields: str | None = None,
	) -> dict[str, Any]:
		cart = self._cart(reference, quotation).model_dump(mode="json")
		return self._select_fields(cart, fields)

	@staticmethod
	def _cart(reference: "Document", quotation: "Document") -> StoreCart:
		item_subtotal = flt(quotation.net_total)
		original_item_subtotal = flt(quotation.total)
		tax_total = flt(quotation.total_taxes_and_charges)
		discount_total = flt(quotation.discount_amount)
		updated_at = max(get_datetime(reference.modified), get_datetime(quotation.modified))
		return StoreCart(
			id=reference.cart_id,
			region_id=reference.region_id or None,
			customer_id=reference.owner_customer or None,
			sales_channel_id=reference.sales_channel_id or None,
			email=quotation.contact_email or None,
			currency_code=quotation.currency.lower(),
			metadata=json.loads(reference.metadata) if reference.metadata else None,
			locale=reference.locale or None,
			billing_address=serialize_address(quotation.customer_address),
			shipping_address=serialize_address(quotation.shipping_address_name),
			created_at=min(get_datetime(reference.creation), get_datetime(quotation.creation)),
			updated_at=updated_at,
			items=CartSerializer._items(reference, quotation),
			shipping_methods=[],
			promotions=CartSerializer._promotions(quotation),
			original_item_total=original_item_subtotal + tax_total,
			original_item_subtotal=original_item_subtotal,
			original_item_tax_total=tax_total,
			item_total=item_subtotal + tax_total,
			item_subtotal=item_subtotal,
			item_tax_total=tax_total,
			original_total=flt(quotation.grand_total) + discount_total,
			original_subtotal=original_item_subtotal,
			original_tax_total=tax_total,
			total=flt(quotation.grand_total),
			subtotal=item_subtotal,
			tax_total=tax_total,
			discount_total=discount_total,
		)

	@staticmethod
	def _promotions(quotation: "Document") -> list[StoreCartPromotion]:
		"""Serialize the applied coupon derived from the Quotation.

		The Quotation carries at most one ``Coupon Code`` link (ERPNext's
		native model), so the list holds zero or one entry. Only stable
		identity fields are derived; discount amounts come from the ERPNext
		totals already serialized into the cart's money fields.
		"""
		applied = quotation.get("coupon_code")
		if not applied:
			return []
		code = frappe.db.get_value("Coupon Code", applied, "coupon_code")
		if not code:
			return []
		return [StoreCartPromotion(id=applied, code=code, is_automatic=False)]

	@staticmethod
	def _items(reference: "Document", quotation: "Document") -> list[StoreCartLineItem]:
		"""Serialize mapped lines joined to Quotation rows, in Quotation row order.

		Money values come straight from the ERPNext row calculations (price
		list, pricing rules, discounts). Conservative defaults: the public
		variant id equals the enabled ERPNext Item code (Phase 2). Per-line
		``tax_total`` is the ERPNext-calculated tax allocation for that row
		(see :meth:`line_tax_allocations`); the line ``total`` is the
		after-discount net amount plus that tax allocation.
		"""
		mappings = {
			mapping.quotation_item: mapping
			for mapping in frappe.get_all(
				"Ceto Cart Line Item Reference",
				filters={"cart_reference": reference.name},
				fields=["name", "line_id", "quotation_item", "metadata", "creation", "modified"],
			)
		}
		items: list[StoreCartLineItem] = []
		tax_allocations = CartSerializer.line_tax_allocations(quotation)
		for row in quotation.items:
			mapping = mappings.get(row.name)
			if mapping is None:
				continue
			net_amount = flt(row.net_amount) or flt(row.amount)
			tax_total = CartSerializer.row_tax_total(tax_allocations, row)
			items.append(
				StoreCartLineItem(
					id=mapping.line_id,
					cart_id=reference.cart_id,
					title=row.item_name or row.item_code,
					product_id=row.item_code,
					product_title=row.item_name,
					variant_id=row.item_code,
					variant_title=row.item_name,
					thumbnail=row.image or None,
					quantity=int(row.qty or 0),
					metadata=json.loads(mapping.metadata) if mapping.metadata else None,
					unit_price=flt(row.net_rate) or flt(row.rate),
					original_unit_price=flt(row.price_list_rate) or flt(row.rate),
					subtotal=net_amount,
					discount_total=flt(row.discount_amount),
					tax_total=tax_total,
					total=net_amount + tax_total,
					created_at=get_datetime(mapping.creation),
					updated_at=get_datetime(mapping.modified),
				)
			)
		return items

	@staticmethod
	def line_tax_allocations(quotation: "Document") -> dict[str, float]:
		"""Map ERPNext tax allocations onto line keys.

		The primary source is the ERPNext controller-produced
		``item_wise_tax_details`` child table (one row per item row / tax row,
		including negative deduction rows). As a fallback for documents that
		only carry the legacy ``item_wise_tax_detail`` JSON on each tax row,
		that field is parsed and summed the same way. Keys are Quotation Item
		row names when possible, else item codes; no tax rate is ever invented.
		"""
		allocations = CartSerializer._allocations_from_tax_details(quotation)
		if not allocations:
			allocations = CartSerializer._allocations_from_legacy_tax_detail(quotation)
		return allocations

	@staticmethod
	def _allocations_from_tax_details(quotation: "Document") -> dict[str, float]:
		allocations: dict[str, float] = {}
		for detail in quotation.get("item_wise_tax_details") or []:
			item_row = detail.get("item_row")
			if not item_row:
				continue
			allocations[item_row] = flt(allocations.get(item_row)) + flt(detail.get("amount"))
		return allocations

	@staticmethod
	def _allocations_from_legacy_tax_detail(quotation: "Document") -> dict[str, float]:
		allocations: dict[str, float] = {}
		for tax in quotation.get("taxes") or []:
			detail = tax.get("item_wise_tax_detail")
			if isinstance(detail, str):
				try:
					detail = json.loads(detail)
				except (TypeError, ValueError):
					continue
			if not isinstance(detail, dict):
				continue
			for key, value in detail.items():
				if isinstance(value, (list, tuple)) and len(value) > 1:
					value = value[1]
				allocations[key] = flt(allocations.get(key)) + flt(value)
		return allocations

	@staticmethod
	def row_tax_total(allocations: dict[str, float], row: "Document") -> float:
		"""Return the ERPNext tax allocated to ``row`` (0 when unallocated)."""
		if row.name in allocations:
			return flt(allocations[row.name])
		return flt(allocations.get(row.item_code))

	@staticmethod
	def _select_fields(cart: dict[str, Any], fields: str | None) -> dict[str, Any]:
		if not fields:
			return cart

		tokens = [token.strip() for token in fields.split(",") if token.strip()]
		plain_fields = {CartSerializer._field_name(token) for token in tokens if token[0] not in "+-*"}
		selected = plain_fields or set(cart)
		for token in tokens:
			field = CartSerializer._field_name(token)
			if field not in cart:
				raise InvalidDataError(f"Unknown cart field: {field}")
			if token.startswith("-"):
				selected.discard(field)
			else:
				selected.add(field)
		return {key: value for key, value in cart.items() if key in selected}

	@staticmethod
	def _field_name(token: str) -> str:
		field = token.lstrip("+-*").split(".", 1)[0]
		if not field:
			raise InvalidDataError("Cart fields must not be empty")
		return field
