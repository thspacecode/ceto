import json
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import flt, get_datetime

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.addresses import serialize_address
from ceto.services.carts.credits import AppliedCredit, CartCredits
from ceto.services.carts.shipping import AppliedShippingCharge, CartShipping
from ceto.types.http.store.carts import (
	StoreCart,
	StoreCartCreditLine,
	StoreCartGiftCard,
	StoreCartLineItem,
	StoreCartPromotion,
	StoreCartShippingMethod,
)

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
		return self.select_fields(cart, fields)

	@staticmethod
	def _cart(reference: "Document", quotation: "Document") -> StoreCart:
		item_subtotal = flt(quotation.net_total)
		original_item_subtotal = flt(quotation.total)
		discount_total = flt(quotation.discount_amount)
		updated_at = max(get_datetime(reference.modified), get_datetime(quotation.modified))
		shipping_charge = CartShipping.applied_charge(quotation)
		shipping_total = flt(shipping_charge.amount) if shipping_charge else 0.0
		credits = CartCredits.applied_credits(quotation.name)
		gift_card_total = flt(sum(credit.amount for credit in credits if credit.reference == "gift-card"))
		# Every open hold — gift card or store credit — is one credit line, so
		# the Medusa credit-line total is the sum of all of them (it includes
		# ``gift_card_total``).
		credit_line_total = flt(sum(credit.amount for credit in credits))
		deduction_rows = CartCredits.deduction_rows(quotation)
		deduction_total = flt(sum(flt(row.tax_amount) for row in deduction_rows))
		# ERPNext books the Shipping Rule charge as an ``Actual`` row inside
		# the ``taxes`` table, and the credit deductions are negative rows on
		# the same table; both spread proportionally over the item tax
		# allocation, so both are carved out of the tax fields Medusa reads.
		# ``total`` stays ERPNext's grand total (deductions included) and the
		# subtotal is reconciled from the item and shipping subtotals.
		tax_total = flt(quotation.total_taxes_and_charges) - shipping_total - deduction_total
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
			items=CartSerializer._items(
				reference,
				quotation,
				shipping_charge,
				{row.name for row in deduction_rows}
				| ({shipping_charge.tax_row.name} if shipping_charge else set()),
			),
			shipping_methods=CartSerializer._shipping_methods(reference, shipping_charge),
			promotions=CartSerializer._promotions(quotation),
			gift_cards=CartSerializer._gift_cards(credits),
			credit_lines=CartSerializer._credit_lines(reference, credits),
			original_item_total=original_item_subtotal + tax_total,
			original_item_subtotal=original_item_subtotal,
			original_item_tax_total=tax_total,
			item_total=item_subtotal + tax_total,
			item_subtotal=item_subtotal,
			item_tax_total=tax_total,
			original_total=flt(quotation.grand_total) + discount_total,
			original_subtotal=original_item_subtotal + shipping_total,
			original_tax_total=tax_total,
			total=flt(quotation.grand_total),
			subtotal=item_subtotal + shipping_total,
			tax_total=tax_total,
			discount_total=discount_total,
			gift_card_total=gift_card_total,
			gift_card_tax_total=0,
			credit_line_total=credit_line_total,
			shipping_total=shipping_total,
			shipping_subtotal=shipping_total,
			shipping_tax_total=0,
			original_shipping_total=shipping_total,
			original_shipping_subtotal=shipping_total,
			original_shipping_tax_total=0,
		)

	@staticmethod
	def _promotions(quotation: "Document") -> list[StoreCartPromotion]:
		"""Serialize the applied coupon; zero or one entry.

		The Quotation carries at most one ``Coupon Code`` link (ERPNext's
		native model). Only identity fields are derived; discount amounts
		come from the ERPNext totals already serialized into the cart.
		"""
		applied = quotation.get("coupon_code")
		if not applied:
			return []
		code = frappe.db.get_value("Coupon Code", applied, "coupon_code")
		if not code:
			return []
		return [StoreCartPromotion(id=applied, code=code, is_automatic=False)]

	@staticmethod
	def _gift_cards(credits: list[AppliedCredit]) -> list[StoreCartGiftCard]:
		"""Serialize the applied gift cards derived from the open holds.

		Codes are stored hash-only, so the serialized ``code`` is the wallet's
		masked hint; clients remove an applied card by resubmitting the
		original code, never the hint.
		"""
		return [
			StoreCartGiftCard(code=credit.code_hint or "")
			for credit in credits
			if credit.reference == "gift-card"
		]

	@staticmethod
	def _credit_lines(reference: "Document", credits: list[AppliedCredit]) -> list[StoreCartCreditLine]:
		"""Serialize the cart's open credit holds as core ``credit_lines``.

		Every open hold — gift card or store credit — is one credit line in
		application order; the ``reference_id`` is the backing wallet's
		public id. Released or consumed holds stop serializing.
		"""
		return [
			StoreCartCreditLine(
				id=credit.credit_line_id,
				cart_id=reference.cart_id,
				amount=credit.amount,
				reference=credit.reference,
				reference_id=credit.wallet,
				created_at=credit.creation,
				updated_at=credit.modified,
			)
			for credit in credits
		]

	@staticmethod
	def _shipping_methods(
		reference: "Document",
		charge: AppliedShippingCharge | None,
	) -> list[StoreCartShippingMethod]:
		"""Serialize the applied Shipping Rule charge; zero or one entry.

		``None`` charge means no shipping to report: no rule, a rule deleted
		after applying, or no charge row (an itemless cart). The option
		reference is the rule the Quotation links, the method identity is the
		applied charge row, and the money fields are the ERPNext-calculated
		row amount — no amount or tax is derived here (see
		:cmod:`ceto.services.carts.shipping` for the row's limitations), and
		the row also timestamps the method.
		"""
		if charge is None:
			return []
		amount = flt(charge.amount)
		return [
			StoreCartShippingMethod(
				id=charge.tax_row.name,
				cart_id=reference.cart_id,
				shipping_option_id=charge.rule,
				name=charge.label,
				amount=amount,
				subtotal=amount,
				total=amount,
				tax_total=0,
				is_tax_inclusive=False,
				created_at=get_datetime(charge.tax_row.creation),
				updated_at=get_datetime(charge.tax_row.modified),
			)
		]

	@staticmethod
	def _items(
		reference: "Document",
		quotation: "Document",
		shipping_charge: AppliedShippingCharge | None = None,
		exclude_tax_rows: set[str] | None = None,
	) -> list[StoreCartLineItem]:
		"""Serialize mapped lines joined to Quotation rows, in Quotation row order.

		Money values come straight from the ERPNext row calculations (price
		list, pricing rules, discounts). Conservative defaults: the public
		variant id equals the enabled ERPNext Item code (Phase 2). Per-line
		``tax_total`` is the ERPNext-calculated tax allocation for that row
		(see :meth:`_line_tax_allocations`) with ``exclude_tax_rows``
		removed — the applied Shipping Rule charge and the negative credit
		deduction rows are cart charges, not item tax, even though ERPNext
		spreads their ``Actual`` amounts proportionally over the rows — and
		the line ``total`` is the after-discount net amount plus that tax
		allocation.
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
		tax_allocations = CartSerializer._line_tax_allocations(quotation, exclude_tax_rows)
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
	def _line_tax_allocations(
		quotation: "Document", exclude_tax_rows: set[str] | None = None
	) -> dict[str, float]:
		"""Map ERPNext tax allocations onto line keys.

		The primary source is the ERPNext controller-produced
		``item_wise_tax_details`` child table (one row per item row / tax row,
		including negative deduction rows). As a fallback for documents that
		only carry the legacy ``item_wise_tax_detail`` JSON on each tax row,
		that field is parsed and summed the same way. Keys are Quotation Item
		row names when possible, else item codes; no tax rate is ever invented.

		``exclude_tax_rows`` drops taxes rows from the allocation — the
		applied Shipping Rule charge and the negative credit deduction rows,
		whose ``Actual`` amounts spread proportionally over the item rows
		even though they are cart charges, not item tax.
		"""
		allocations = CartSerializer._allocations_from_tax_details(quotation, exclude_tax_rows)
		if not allocations:
			allocations = CartSerializer._allocations_from_legacy_tax_detail(quotation, exclude_tax_rows)
		return allocations

	@staticmethod
	def _allocations_from_tax_details(
		quotation: "Document", exclude_tax_rows: set[str] | None = None
	) -> dict[str, float]:
		allocations: dict[str, float] = {}
		for detail in quotation.get("item_wise_tax_details") or []:
			if exclude_tax_rows and detail.get("tax_row") in exclude_tax_rows:
				continue
			item_row = detail.get("item_row")
			if not item_row:
				continue
			allocations[item_row] = flt(allocations.get(item_row)) + flt(detail.get("amount"))
		return allocations

	@staticmethod
	def _allocations_from_legacy_tax_detail(
		quotation: "Document", exclude_tax_rows: set[str] | None = None
	) -> dict[str, float]:
		allocations: dict[str, float] = {}
		for tax in quotation.get("taxes") or []:
			if exclude_tax_rows and tax.get("name") in exclude_tax_rows:
				continue
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
	def select_fields(cart: dict[str, Any], fields: str | None, *, entity: str = "cart") -> dict[str, Any]:
		"""Apply the shared ``fields`` selector to one serialized entity.

		The completion response is a union of two entities (the placed order
		or the refused cart), so the selector takes an ``entity`` label that
		only names the field in the error messages.
		"""
		if not fields:
			return cart

		tokens = [token.strip() for token in fields.split(",") if token.strip()]
		plain_fields = {
			CartSerializer._field_name(token, entity) for token in tokens if token[0] not in "+-*"
		}
		selected = plain_fields or set(cart)
		for token in tokens:
			field = CartSerializer._field_name(token, entity)
			if field not in cart:
				raise InvalidDataError(f"Unknown {entity} field: {field}")
			if token.startswith("-"):
				selected.discard(field)
			else:
				selected.add(field)
		return {key: value for key, value in cart.items() if key in selected}

	@staticmethod
	def _field_name(token: str, entity: str = "cart") -> str:
		field = token.lstrip("+-*").split(".", 1)[0]
		if not field:
			raise InvalidDataError(f"{entity.capitalize()} fields must not be empty")
		return field
