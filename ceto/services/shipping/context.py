"""Frozen quote context shared by every shipping provider.

One quote context carries everything a provider may price against: the
cart identity with its region and sales channel, the shipping-address
country, the ERPNext-relevant totals and the currency frame. It is a
frozen value object built from the cart's two committed records — the
``Ceto Cart Reference`` (the public identity) and the Quotation (the
document ERPNext itself prices) — and providers read the cart through it
without ever mutating it.

The ERPNext-facing columns mirror exactly what ``ShippingRule.apply``
reads: ``base_net_total`` (company currency) for ``Net Total`` conditions,
``total_net_weight`` for ``Net Weight`` conditions, and the
``currency``/``company_currency``/``conversion_rate`` frame for the
company-currency conversion of the resolved rate. A missing conversion
rate is the cart surface's pinned "same currency" (rate 1), so the
builder normalizes a falsy rate to 1.0 instead of letting the adapter
divide by zero.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import frappe
from erpnext import get_company_currency
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError

if TYPE_CHECKING:
	from frappe.model.document import Document


@dataclass(frozen=True, slots=True)
class ShippingQuoteContext:
	"""Everything a provider prices against, immutable by contract."""

	cart_id: str
	company: str
	company_currency: str
	currency: str
	conversion_rate: float
	base_net_total: float
	total_net_weight: float
	country: str | None = None
	region_id: str | None = None
	sales_channel_id: str | None = None

	@classmethod
	def from_cart(cls, reference: "Document", quotation: "Document") -> "ShippingQuoteContext":
		"""Build the context of a cart from its reference and Quotation.

		The quotation must already carry its totals (the saved cart
		document). A cart without an identity, company or currency resolves
		nothing a provider could price and is refused like any broken cart
		anchor.
		"""
		cart_id = str(reference.get("cart_id") or "").strip()
		if not cart_id:
			raise InvalidDataError("Shipping options require a cart")
		company = str(quotation.get("company") or "").strip()
		currency = str(quotation.get("currency") or "").strip()
		if not company or not currency:
			raise InvalidDataError(f"Cart {cart_id} has no company or currency to price against")
		address = quotation.get("shipping_address_name")
		return cls(
			cart_id=cart_id,
			company=company,
			company_currency=str(get_company_currency(company) or ""),
			currency=currency,
			conversion_rate=flt(quotation.get("conversion_rate")) or 1.0,
			base_net_total=flt(quotation.get("base_net_total")),
			total_net_weight=flt(quotation.get("total_net_weight")),
			country=frappe.db.get_value("Address", address, "country") if address else None,
			region_id=reference.get("region_id"),
			sales_channel_id=reference.get("sales_channel_id"),
		)
