import json
from typing import TYPE_CHECKING, Any

from frappe.utils import flt, get_datetime

from ceto.routing.exceptions import InvalidDataError
from ceto.types.http.store.carts import StoreCart

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
			created_at=min(get_datetime(reference.creation), get_datetime(quotation.creation)),
			updated_at=updated_at,
			items=[],
			shipping_methods=[],
			promotions=[],
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
