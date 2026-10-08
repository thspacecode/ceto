"""Cart-scoped temporary Address management for Ceto carts.

Phase 3 implements Medusa cart addresses on top of the Phase 1 cart core:

- Object-form address payloads create **cart-scoped temporary** ERPNext
  ``Address`` records (title ``Cart <cart_id>``, Dynamic Link to the Quotation
  only, never to a Customer).
- ID-form address references are accepted only when the Address already
  belongs to the explicit cart (Quotation Dynamic Link) or to the cart's
  claimed customer (``Ceto Cart Reference.owner_customer``). Anything else is
  rejected to prevent cross-cart/address disclosure.
- The resolved Address is linked into the Quotation (``customer_address`` for
  billing, ``shipping_address_name`` for shipping); ERPNext keeps the
  read-only ``address_display`` / ``shipping_address`` snapshot fields in
  sync on save.
- ``country_code`` is resolved from the ISO 3166-1 alpha-2 code on the
  ERPNext ``Country`` master.

Per ``docs/carts/field-mapping.md`` the Medusa ``first_name`` / ``last_name``
/ ``company`` values collapse into the cart-scoped ``address_title`` and are
therefore not serialized back until the claim/completion phase creates
customer-linked copies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.addresses import is_customer_address, resolve_country

if TYPE_CHECKING:
	from frappe.model.document import Document

	from ceto.types.http.store.carts.payloads import (
		StoreCartAddressPayload,
		StoreCreateCart,
		StoreUpdateCart,
	)

#: (payload field, Quotation link field, ERPNext address type)
_ADDRESS_SLOTS = (
	("billing_address", "customer_address", "Billing"),
	("shipping_address", "shipping_address_name", "Shipping"),
)

_ADDRESS_FIELDS = ("address_1", "address_2", "city", "province", "postal_code", "phone")


class CartAddresses:
	"""Create and resolve cart addresses for the create/update cart flows."""

	def apply(
		self,
		reference: "Document",
		quotation: "Document",
		payload: "StoreCreateCart | StoreUpdateCart",
	) -> None:
		"""Link the payload's billing/shipping addresses onto the Quotation.

		Runs inside the caller's privileged scope (trusted controller work);
		the caller is responsible for saving the Quotation afterwards.
		"""
		fields = payload.model_fields_set
		for field, link_field, address_type in _ADDRESS_SLOTS:
			if field not in fields:
				continue
			value = getattr(payload, field)
			# Detach the previous address in the database first: ERPNext's
			# delete-time link check reads the live Quotation row, so the
			# stale link must be gone before a temporary is cleaned up.
			previous = quotation.get(link_field)
			if previous:
				quotation.db_set(link_field, None, notify=False)
			if value is None:
				self.discard_temporary(quotation, previous)
				continue
			resolved = self._resolve(reference, quotation, value, address_type)
			self.discard_temporary(quotation, previous)
			setattr(quotation, link_field, resolved)

	@staticmethod
	def enforce_cleared(quotation: "Document", payload: "StoreCreateCart | StoreUpdateCart") -> None:
		"""Re-clear address slots the payload set to ``None`` after a save.

		ERPNext's ``SellingController.set_customer_address`` refills empty
		address links from the party's default address
		(``update_if_missing``), and cart temporaries are linked to the cart's
		guest Customer, so a cleared slot silently resurrects as the other
		slot's temporary. Clearing the link and display fields again after
		the controller save keeps the explicit ``None`` semantics of the
		Medusa payload.
		"""
		displays = {"customer_address": "address_display", "shipping_address_name": "shipping_address"}
		for field, link_field, _address_type in _ADDRESS_SLOTS:
			if field in payload.model_fields_set and getattr(payload, field) is None:
				quotation.db_set(link_field, None, notify=False)
				quotation.db_set(displays[link_field], None, notify=False)

	def attach_owner(self, quotation: "Document", customer: str) -> None:
		"""Re-scope the Quotation's address links to the claiming customer.

		Implements Recorded Decision 4 (``docs/carts/field-mapping.md``): every
		cart-scoped temporary address still attached on claim is copied to a
		new ``Address`` linked **only** to the claiming Customer (never to the
		shared guest Customer or the Quotation, so no other cart can reach
		it), the billing/shipping slots are relinked to that copy — one shared
		copy when both slots reference the same temporary — and the temporary
		itself is deleted. Addresses already linked to ``customer`` stay
		attached unchanged; anything else is detached without being copied.
		"""
		displays = {"customer_address": "address_display", "shipping_address_name": "shipping_address"}
		attached = {quotation.get(field) for field in displays} - {None}
		copies: dict[str, str] = {}
		for address_name in attached:
			if is_customer_address(address_name, customer):
				continue
			if not CartAddresses.is_cart_temporary(address_name, quotation.name):
				# Neither the customer's nor this cart's temporary: never
				# attach it to the claiming customer.
				for link_field, display_field in displays.items():
					if quotation.get(link_field) == address_name:
						quotation.db_set(link_field, None, notify=False)
						quotation.db_set(display_field, None, notify=False)
				continue
			if address_name not in copies:
				copies[address_name] = CartAddresses._copy_for_customer(address_name, customer)
			for link_field, display_field in displays.items():
				if quotation.get(link_field) == address_name:
					quotation.db_set(link_field, copies[address_name], notify=False)
					# ERPNext re-renders the display snapshot on save.
					quotation.db_set(display_field, None, notify=False)
		# Deleting only after every referencing slot points at the copy keeps
		# ERPNext's delete-time link check (live Quotation row) satisfied.
		for original in copies:
			CartAddresses.discard_temporary(quotation, original)

	@staticmethod
	def is_cart_temporary(address_name: str, quotation_name: str) -> bool:
		"""Return whether ``address_name`` is this cart's scoped temporary."""
		title = frappe.db.get_value("Address", address_name, "address_title")
		if not title or not title.startswith("Cart "):
			return False
		return bool(
			frappe.db.exists(
				"Dynamic Link",
				{
					"parenttype": "Address",
					"parent": address_name,
					"link_doctype": "Quotation",
					"link_name": quotation_name,
				},
			)
		)

	@staticmethod
	def _copy_for_customer(address_name: str, customer: str) -> str:
		"""Clone a cart temporary as an Address owned by ``customer``."""
		source = frappe.get_doc("Address", address_name)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": source.address_title,
				"address_type": source.address_type,
				"address_line1": source.address_line1,
				"address_line2": source.address_line2,
				"city": source.city,
				"state": source.state,
				"pincode": source.pincode,
				"country": source.country,
				"phone": source.phone,
				"is_primary_address": 0,
				"is_shipping_address": 0,
				"links": [
					# The copy is customer-owned only: no guest Customer link
					# (shared across all guest carts) and no Quotation link,
					# so it can never leak into another cart.
					{"link_doctype": "Customer", "link_name": customer},
				],
			}
		)
		address.flags.ignore_permissions = True
		address.insert()
		return address.name

	def _resolve(
		self,
		reference: "Document",
		quotation: "Document",
		value: StoreCartAddressPayload | str,
		address_type: str,
	) -> str:
		if isinstance(value, str):
			return self._link_existing(reference, quotation, value)
		return self._create_temporary(reference, quotation, value, address_type)

	@staticmethod
	def _create_temporary(
		reference: "Document",
		quotation: "Document",
		payload: StoreCartAddressPayload,
		address_type: str,
	) -> str:
		if not payload.country_code:
			raise InvalidDataError("Address country_code is required")
		country = resolve_country(payload.country_code)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Cart {reference.cart_id}",
				"address_type": address_type,
				"address_line1": payload.address_1,
				"address_line2": payload.address_2,
				"city": payload.city,
				"state": payload.province,
				"pincode": payload.postal_code,
				"country": country,
				"phone": payload.phone,
				"is_primary_address": 0,
				"is_shipping_address": 0,
				"links": [
					# ERPNext validates that the Quotation's addresses belong to
					# its party; each cart has a unique guest Customer, so this
					# link stays cart-scoped.
					{"link_doctype": "Customer", "link_name": quotation.party_name},
					{"link_doctype": "Quotation", "link_name": reference.quotation},
				],
			}
		)
		address.flags.ignore_permissions = True
		address.insert()
		return address.name

	def _link_existing(self, reference: "Document", quotation: "Document", address_id: str) -> str:
		try:
			address = frappe.get_doc("Address", address_id)
		except frappe.DoesNotExistError:
			raise InvalidDataError(f"Unknown address: {address_id}") from None
		if not self.belongs_to_party(address.name, quotation.name, reference.owner_customer):
			raise InvalidDataError("Address does not belong to this cart")
		return address.name

	@staticmethod
	def belongs_to_party(address_name: str, quotation_name: str, owner_customer: str | None) -> bool:
		links = frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Address", "parent": address_name},
			fields=["link_doctype", "link_name"],
		)
		for link in links:
			if link.link_doctype == "Quotation" and link.link_name == quotation_name:
				return True
			if owner_customer and link.link_doctype == "Customer" and link.link_name == owner_customer:
				return True
		return False

	@staticmethod
	def discard_temporary(quotation: "Document", previous: str | None) -> None:
		"""Delete the previous cart-scoped temporary address, if it is one."""
		if not previous:
			return
		cart_prefix = "Cart "
		title = frappe.db.get_value("Address", previous, "address_title")
		if not title or not title.startswith(cart_prefix):
			return
		linked = frappe.db.exists(
			"Dynamic Link",
			{
				"parenttype": "Address",
				"parent": previous,
				"link_doctype": "Quotation",
				"link_name": quotation.name,
			},
		)
		if linked:
			frappe.delete_doc("Address", previous, ignore_permissions=True)
