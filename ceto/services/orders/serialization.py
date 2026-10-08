"""Order domain service for Ceto: serialize a completed cart's placed order.

The completion flow books a ``Ceto Order Reference`` (the public ``order_…``
id), maps the submitted cart Quotation into a submitted ERPNext Sales Order
and consumes the cart's credit holds. This module reads that state back:

- Identity and cart context (region, sales channel, metadata) come from the
  completed cart's ``Ceto Cart Reference``. The cart's ``locale``
  is deliberately **not** carried over: the pinned ``StoreOrder`` of
  ``@medusajs/types@2.21.1`` has no locale column — it is a cart-only
  column — so the order never reports one.
- Ownership (the Medusa ``customer_id``) comes from the order reference's
  effective owner (``OrderOwnership``): the ``owner_customer`` snapshot the
  completion booked, with the completed cart as the legacy fallback. The
  completion snapshots the cart's owner at birth, so the serialized order
  is unchanged by the switch — for records born with the snapshot and for
  Phase 6 legacy rows alike.
- The optional embedded ``customer`` is the pinned ``StoreCustomer`` the
  customers contract serves: the cart's owner resolves through the shared
  identity resolver and its ``Ceto Customer Reference`` and serializes with
  the shared ``CustomerSerializer``. Guests and reference-less owners stay
  ``None`` — no identity is invented — while ``customer_id`` keeps the
  historical ERPNext Customer-name mapping (the recorded compatibility
  deviation, decision 10 of ``docs/carts/field-mapping.md``).
- Money, lines, addresses and the applied shipping charge come from the
  Sales Order the ERPNext mapper produced — nothing is re-derived here.
- The consumed credit holds (order-credit reads via
  ``CartCredits.consumed_credits``) reappear as the order's
  ``gift_card_total`` / ``credit_line_total``, the same carve-out
  arithmetic the cart serializer uses, so the Medusa summary identity
  ``total + discount_total + credit_line_total == subtotal + tax_total``
  holds for the order as well: the negative deduction rows ride the mapper
  onto the Sales Order and are carved out of the tax fields.

Deliberately omitted (Recorded Decision 9): ``display_id`` and
``custom_display_id`` — the ERPNext Sales Order name stays internal to the
order reference. The pinned ``item_discount_total`` /
``shipping_discount_total`` split is omitted too: ERPNext carries a single
order-level ``discount_amount`` (the coupon/additional discount; per-row
pricing discounts ride the item rows) and gives the Shipping Rule charge no
discount bucket, so the Medusa item/shipping discount split cannot be
derived without inventing numbers — ``discount_total`` keeps the
order-level amount.
"""

import json
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import flt, get_datetime

from ceto.routing.exceptions import InternalServerError
from ceto.services.addresses import serialize_address
from ceto.services.carts.credits import CartCredits
from ceto.services.carts.serialization import CartSerializer
from ceto.services.carts.shipping import AppliedShippingCharge, CartShipping
from ceto.services.customers.identity import find_customer_reference
from ceto.services.customers.serialization import CustomerSerializer
from ceto.services.orders.ownership import OrderOwnership
from ceto.types.http.store.customers.entities import StoreCustomer
from ceto.types.http.store.orders import (
	StoreOrder,
	StoreOrderAddress,
	StoreOrderLineItem,
	StoreOrderShippingMethod,
)

if TYPE_CHECKING:
	from frappe.model.document import Document

	from ceto.services.carts.credits import AppliedCredit
	from ceto.services.orders.context import OrderPageContext


class OrderSerializer:
	"""Serialize the placed order of a completed cart from its records."""

	def serialize(
		self,
		order_reference: "Document",
		sales_order: "Document",
		reference: "Document",
		*,
		context: "OrderPageContext | None" = None,
	) -> dict[str, Any]:
		"""Return the pinned ``StoreOrder`` JSON for the completed cart.

		``order_reference`` is the ``Ceto Order Reference`` the completion
		booked, ``sales_order`` the ERPNext identity it stands for and
		``reference`` the completed cart's ``Ceto Cart Reference`` (the cart
		context the Sales Order never carried). ``context`` is an optional
		:class:`OrderPageContext` that serves the child reads (line
		mappings, addresses, consumed credits, shipping rule) from bulk
		loads; without one every lookup happens per order — the output is
		identical either way.
		"""
		return self._order(order_reference, sales_order, reference, context).model_dump(mode="json")

	@staticmethod
	def _order(
		order_reference: "Document",
		sales_order: "Document",
		reference: "Document",
		context: "OrderPageContext | None" = None,
	) -> StoreOrder:
		shipping_charge = OrderSerializer._shipping_charge(sales_order, context)
		shipping_total = flt(shipping_charge.amount) if shipping_charge else 0.0
		deduction_rows = CartCredits.deduction_rows(sales_order)
		deduction_total = flt(sum(flt(row.tax_amount) for row in deduction_rows))
		# Same carve-out as the cart: the Shipping Rule charge and the
		# consumed credit deductions are ``Actual`` rows inside the ERPNext
		# totals; the order keeps ``total`` on the ERPNext grand total.
		tax_total = flt(sales_order.total_taxes_and_charges) - shipping_total - deduction_total
		item_subtotal = flt(sales_order.net_total)
		original_item_subtotal = flt(sales_order.total)
		discount_total = flt(sales_order.discount_amount)
		credits = OrderSerializer._consumed_credits(reference, context)
		gift_card_total = flt(sum(credit.amount for credit in credits if credit.reference == "gift-card"))
		# Every consumed hold — gift card or store credit — is one credit
		# line of the order (it includes ``gift_card_total``).
		credit_line_total = flt(sum(credit.amount for credit in credits))
		exclude_tax_rows = {row.name for row in deduction_rows} | (
			{shipping_charge.tax_row.name} if shipping_charge else set()
		)
		return StoreOrder(
			id=order_reference.order_id,
			region_id=reference.region_id or None,
			customer_id=OrderOwnership.effective_owner(order_reference),
			customer=OrderSerializer._customer(reference.owner_user, context),
			sales_channel_id=reference.sales_channel_id or None,
			email=sales_order.contact_email or None,
			currency_code=sales_order.currency.lower(),
			metadata=json.loads(reference.metadata) if reference.metadata else None,
			billing_address=OrderSerializer._order_address(sales_order.customer_address, context),
			shipping_address=OrderSerializer._order_address(sales_order.shipping_address_name, context),
			created_at=get_datetime(order_reference.creation),
			updated_at=get_datetime(order_reference.modified),
			items=OrderSerializer._items(
				reference,
				order_reference.order_id,
				sales_order,
				shipping_charge,
				exclude_tax_rows,
				context,
			),
			shipping_methods=OrderSerializer._shipping_methods(order_reference, shipping_charge),
			original_item_total=original_item_subtotal + tax_total,
			original_item_subtotal=original_item_subtotal,
			original_item_tax_total=tax_total,
			item_total=item_subtotal + tax_total,
			item_subtotal=item_subtotal,
			item_tax_total=tax_total,
			original_total=flt(sales_order.grand_total) + discount_total,
			original_subtotal=original_item_subtotal + shipping_total,
			original_tax_total=tax_total,
			total=flt(sales_order.grand_total),
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
	@staticmethod
	def _shipping_charge(
		sales_order: "Document", context: "OrderPageContext | None"
	) -> "AppliedShippingCharge | None":
		"""Resolve the applied Shipping Rule charge, page-context aware."""
		if context is not None:
			return context.shipping_charge(sales_order)
		return CartShipping.applied_charge(sales_order)

	@staticmethod
	def _consumed_credits(reference: "Document", context: "OrderPageContext | None") -> "list[AppliedCredit]":
		"""Resolve the consumed credit holds, page-context aware."""
		if context is not None:
			return context.consumed_credits(reference.quotation)
		return CartCredits.consumed_credits(reference.quotation)

	@staticmethod
	def _customer(owner_user: str | None, context: "OrderPageContext | None" = None) -> StoreCustomer | None:
		"""Serialize the completed cart's owner as the embedded customer.

		The owner resolves through the shared identity resolver and its
		``Ceto Customer Reference`` — the strict customers-contract chain,
		quietly — and serializes with the shared ``CustomerSerializer``, so
		the embedded representation is exactly what the customers routes
		serve, never a re-derived one. Guests (no owner) and owners without
		a reference — a pre-existing ERPNext account linked outside Ceto —
		have no contract-safe ``cus_…`` identity, so the column stays
		``None`` instead of inventing one; ``customer_id`` keeps the
		historical ERPNext Customer-name mapping regardless (Recorded
		Decision 10 of ``docs/carts/field-mapping.md``). With a page
		``context`` the resolution is served from the page's memoized
		owner identity instead of per-order reads.
		"""
		if context is not None:
			return context.customer(owner_user)
		if not owner_user:
			return None
		found = find_customer_reference(owner_user)
		if found is None:
			return None
		identity, reference = found
		return CustomerSerializer.serialize(identity, reference)

	@staticmethod
	def _order_address(
		address_name: str | None, context: "OrderPageContext | None"
	) -> StoreOrderAddress | None:
		"""Serialize a linked Address as the order's pinned address type."""
		address = context.address(address_name) if context is not None else serialize_address(address_name)
		if address is None:
			return None
		return StoreOrderAddress.model_validate(address.model_dump())

	@staticmethod
	def _items(
		reference: "Document",
		order_id: str,
		sales_order: "Document",
		shipping_charge: AppliedShippingCharge | None = None,
		exclude_tax_rows: set[str] | None = None,
		context: "OrderPageContext | None" = None,
	) -> list[StoreOrderLineItem]:
		"""Serialize mapped Sales Order rows in row order, keeping line ids.

		The mapper stamps every Sales Order row with its source Quotation
		Item row, so the cart's ``Ceto Cart Line Item Reference`` mapping
		carries the public ``li_…`` identity over to the order line — the
		same id the client saw on the cart. Money values come straight from
		the ERPNext row calculations copied by the mapper; per-line
		``tax_total`` is the ERPNext tax allocation minus the carved-out
		cart charges (see :meth:`CartSerializer.line_tax_allocations`).
		Line timestamps stay the cart line's: the order line is the same
		commerce line placed.
		"""
		rows = (
			context.line_references(reference.name)
			if context is not None
			else frappe.get_all(
				"Ceto Cart Line Item Reference",
				filters={"cart_reference": reference.name},
				fields=["name", "line_id", "quotation_item", "metadata", "creation", "modified"],
			)
		)
		mappings = {mapping.quotation_item: mapping for mapping in rows}
		items: list[StoreOrderLineItem] = []
		tax_allocations = CartSerializer.line_tax_allocations(sales_order, exclude_tax_rows)
		for row in sales_order.items:
			mapping = mappings.get(row.quotation_item)
			if mapping is None:
				# Defense-in-depth: completion asserts every Sales Order row
				# onto a cart line mapping before the order reference is
				# booked, so an unmapped row reaching this serializer — a
				# mapper-invented free-item row, or a replay over broken
				# mappings — is a broken invariant. Skipping it would ship
				# an order that silently loses or undercounts lines and
				# money; refuse loudly instead (the router renders this as
				# ``500 internal_error`` and rolls the request back).
				raise InternalServerError(
					f"Sales Order {sales_order.name} row {row.item_code or row.name}"
					" has no matching cart line mapping"
				)
			net_amount = flt(row.net_amount) or flt(row.amount)
			tax_total = CartSerializer.row_tax_total(tax_allocations, row)
			items.append(
				StoreOrderLineItem(
					id=mapping.line_id,
					order_id=order_id,
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
	def _shipping_methods(
		order_reference: "Document",
		charge: AppliedShippingCharge | None,
	) -> list[StoreOrderShippingMethod]:
		"""Serialize the Sales Order's Shipping Rule charge row, cart-alike.

		The ERPNext mapper copies the Quotation's ``Shipping Rule`` link and
		its ``Actual`` charge row (amounts included), so the order reports
		the same single method the cart applied: the option reference is the
		rule, the method identity is the applied charge row, and no tax is
		ever allocated onto the row (``is_tax_inclusive`` false).
		"""
		if charge is None:
			return []
		amount = flt(charge.amount)
		return [
			StoreOrderShippingMethod(
				id=charge.tax_row.name,
				order_id=order_reference.order_id,
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
