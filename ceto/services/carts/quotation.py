import secrets
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING

import frappe
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from frappe.utils import getdate, today

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.addresses import CartAddresses
from ceto.services.carts.configuration import CartConfiguration
from ceto.services.carts.line_items import CartLineItems, dump_metadata, merged_metadata
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCreateCart,
	StoreUpdateCart,
	StoreUpdateCartLineItem,
)

if TYPE_CHECKING:
	from frappe.model.document import Document


class CartService:
	def __init__(self, access: CartAccess | None = None) -> None:
		self.access = access or CartAccess()
		self.addresses = CartAddresses()

	def create(self, payload: StoreCreateCart) -> tuple["Document", "Document"]:
		self._reject_deferred_create_fields(payload)
		configuration = CartConfiguration.resolve(
			region_id=payload.region_id,
			sales_channel_id=payload.sales_channel_id,
		)
		self._validate_currency(payload.currency_code, configuration.currency)

		owner_user = self.access.owner_user()
		with as_administrator():
			quotation = self._new_quotation(configuration, payload.email)
			reference = frappe.get_doc(
				{
					"doctype": "Ceto Cart Reference",
					"cart_id": self._new_cart_id(),
					"quotation": quotation.name,
					"owner_user": owner_user,
					"region_id": configuration.region_id,
					"sales_channel_id": configuration.sales_channel_id,
					"locale": payload.locale,
					"metadata": dump_metadata(payload.metadata),
				}
			).insert(ignore_permissions=True)
			# All initial lines are created inside the same transaction as the
			# cart itself; a failure rolls back the whole create.
			for line in payload.items or []:
				CartLineItems.add(reference, quotation, line)
			if (
				"shipping_address" in payload.model_fields_set
				or "billing_address" in payload.model_fields_set
			):
				self.addresses.apply(reference, quotation, payload)
				# Re-saving lets ERPNext refresh the address display snapshots
				# and totals.
				CartLineItems.save(quotation)
				self.addresses.enforce_cleared(quotation, payload)
		return reference, quotation

	def retrieve(self, cart_id: str) -> tuple["Document", "Document"]:
		return self.access.get(cart_id)

	def update(
		self,
		cart_id: str,
		payload: StoreUpdateCart,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Update cart fields inside the cart row lock.

		``guard`` runs against the locked reference before any mutation so
		callers (notably the publishable-key scope check) reject the request
		before a Quotation is touched; checking inside ``lock`` avoids TOCTOU
		races with concurrent scope/cart updates.
		"""
		self._reject_deferred_update_fields(payload)
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with as_administrator():
				self._apply_update(reference, quotation, payload)
				self.addresses.apply(reference, quotation, payload)
				# Shared save helper: keeps the mandatory-items relaxation only
				# while the cart is empty and recomputes totals otherwise.
				CartLineItems.save(quotation)
				self.addresses.enforce_cleared(quotation, payload)
				reference.save(ignore_permissions=True)
			return reference, quotation

	def add_line_item(
		self,
		cart_id: str,
		payload: StoreAddCartLineItem,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document", "Document"]:
		"""Add one line to a locked cart; returns (reference, quotation, mapping).

		``guard`` is validated against the locked reference before any
		mutation, so a wrong-scoped key never modifies the cart.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with as_administrator():
				mapping = CartLineItems.add(reference, quotation, payload)
			return reference, quotation, mapping

	def update_line_item(
		self,
		cart_id: str,
		line_id: str,
		payload: StoreUpdateCartLineItem,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document", "Document"]:
		"""Update one line of a locked cart; returns (reference, quotation, mapping).

		``guard`` is validated against the locked reference before any
		mutation, so a wrong-scoped key never modifies the cart.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with as_administrator():
				mapping = CartLineItems.update(reference, quotation, line_id, payload)
			return reference, quotation, mapping

	def delete_line_item(
		self,
		cart_id: str,
		line_id: str,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document", "Document"]:
		"""Remove one line from a locked cart; returns (reference, quotation, mapping).

		``guard`` is validated against the locked reference before any
		mutation, so a wrong-scoped key never modifies the cart.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with as_administrator():
				mapping = CartLineItems.delete(reference, quotation, line_id)
			return reference, quotation, mapping

	def _apply_update(self, reference: "Document", quotation: "Document", payload: StoreUpdateCart) -> None:
		fields = payload.model_fields_set
		if "region_id" in fields or "sales_channel_id" in fields:
			configuration = CartConfiguration.resolve(
				region_id=payload.region_id if "region_id" in fields else reference.region_id,
				sales_channel_id=(
					payload.sales_channel_id if "sales_channel_id" in fields else reference.sales_channel_id
				),
			)
			self._apply_configuration(quotation, configuration)
			reference.region_id = configuration.region_id
			reference.sales_channel_id = configuration.sales_channel_id

		if "email" in fields:
			quotation.contact_email = str(payload.email) if payload.email else None
		if "locale" in fields:
			reference.locale = payload.locale
		if "metadata" in fields:
			reference.metadata = merged_metadata(reference.metadata, payload.metadata)

	@staticmethod
	def _new_quotation(configuration: CartConfiguration, email: str | None) -> "Document":
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": configuration.guest_customer,
				"order_type": "Shopping Cart",
				"company": configuration.company,
				"currency": configuration.currency,
				"selling_price_list": configuration.selling_price_list,
				"taxes_and_charges": configuration.taxes_and_charges,
				# The template rows are loaded explicitly (with ERPNext's own
				# loader) because set_taxes_and_charges() only appends them when
				# Accounts Settings enables template taxes globally.
				"taxes": get_taxes_and_charges(
					"Sales Taxes and Charges Template", configuration.taxes_and_charges
				)
				if configuration.taxes_and_charges
				else [],
				"territory": configuration.territory,
				"contact_email": str(email) if email else None,
				"transaction_date": today(),
				"valid_till": getdate(today()) + timedelta(days=configuration.valid_for_days),
				"conversion_rate": 1,
				"plc_conversion_rate": 1,
				"total_qty": 0,
				"total": 0,
				"base_total": 0,
				"net_total": 0,
				"base_net_total": 0,
				"total_taxes_and_charges": 0,
				"base_total_taxes_and_charges": 0,
				"grand_total": 0,
				"base_grand_total": 0,
				"rounded_total": 0,
				"base_rounded_total": 0,
				"discount_amount": 0,
				"base_discount_amount": 0,
			}
		)
		# Medusa creates carts before they have lines. CartLineItems.save only
		# keeps this relaxation while the cart has no Quotation Item rows.
		quotation.flags.ignore_mandatory = True
		return quotation.insert(ignore_permissions=True)

	@staticmethod
	def _apply_configuration(quotation: "Document", configuration: CartConfiguration) -> None:
		quotation.company = configuration.company
		quotation.currency = configuration.currency
		quotation.selling_price_list = configuration.selling_price_list
		quotation.taxes_and_charges = configuration.taxes_and_charges
		quotation.territory = configuration.territory

	@staticmethod
	def _validate_currency(requested: str | None, configured: str) -> None:
		if requested and requested.lower() != configured.lower():
			raise InvalidDataError("Cart currency must match the configured price list currency")

	@staticmethod
	def _reject_deferred_create_fields(payload: StoreCreateCart) -> None:
		if payload.promo_codes:
			raise InvalidDataError("Cart promotions are not supported yet")

	@staticmethod
	def _reject_deferred_update_fields(payload: StoreUpdateCart) -> None:
		if payload.promo_codes:
			raise InvalidDataError("Cart promotions are not supported yet")

	@staticmethod
	def _new_cart_id() -> str:
		return f"cart_{secrets.token_hex(16)}"


@contextmanager
def as_administrator():
	"""Run trusted ERPNext controller work with account read access."""
	user = frappe.session.user
	try:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
		yield
	finally:
		frappe.set_user(user)  # nosemgrep: frappe-setuser
