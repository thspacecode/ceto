"""Shared, domain-neutral Address helpers used by more than one Ceto domain.

ERPNext ``Address`` records back more than one Medusa surface — the cart
addresses today, the customer address book next — so three of their concerns
live here instead of inside the cart domain: the ISO 3166-1 alpha-2 code
resolution onto the ERPNext ``Country`` master (:func:`resolve_country`), the
ownership check against the ``Address`` ↔ ``Customer`` Dynamic Link
(:func:`is_customer_address`) and the serialization into the pinned Medusa
address entity (:func:`serialize_address`).
"""

from __future__ import annotations

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.types.http.store.carts.entities import StoreCartAddress


def resolve_country(country_code: str) -> str:
	"""Resolve a Medusa (lowercase ISO alpha-2) country code to ERPNext Country."""
	code = country_code.strip().upper()
	country = frappe.db.get_value("Country", {"code": code}, "name")
	if not country:
		raise InvalidDataError(f"Unknown address country code: {country_code.lower()}")
	return country


def is_customer_address(address_name: str, customer: str | None) -> bool:
	"""Return whether ``address_name`` is linked to ``customer``."""
	if not customer:
		return False
	return bool(
		frappe.db.exists(
			"Dynamic Link",
			{
				"parenttype": "Address",
				"parent": address_name,
				"link_doctype": "Customer",
				"link_name": customer,
			},
		)
	)


def serialize_address(address_name: str | None) -> StoreCartAddress | None:
	"""Serialize a linked ERPNext Address into a Medusa ``StoreCartAddress``."""
	if not address_name:
		return None
	try:
		address = frappe.get_doc("Address", address_name)
	except frappe.DoesNotExistError:
		return None
	customer = next((link.link_name for link in address.links if link.link_doctype == "Customer"), None)
	country_code = frappe.db.get_value("Country", address.country, "code") if address.country else None
	return StoreCartAddress(
		id=address.name,
		customer_id=customer,
		first_name=None,
		last_name=None,
		company=None,
		phone=address.phone or None,
		address_1=address.address_line1 or None,
		address_2=address.address_line2 or None,
		city=address.city or None,
		province=address.state or None,
		postal_code=address.pincode or None,
		country_code=country_code.lower() if country_code else None,
	)
