import secrets
from collections.abc import Callable, Iterator
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
from ceto.services.carts.promotions import CartPromotions
from ceto.services.carts.shipping import CartShippingMethods
from ceto.services.carts.taxes import CartTaxes
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCartAddPromotion,
	StoreCartRemovePromotion,
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
		configuration = CartConfiguration.resolve(
			region_id=payload.region_id,
			sales_channel_id=payload.sales_channel_id,
		)
		self._validate_currency(payload.currency_code, configuration.currency)

		owner_user = self.access.owner_user()
		with privileged_scope():
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
			if payload.promo_codes is not None:
				# Promo codes ride the same create transaction: an invalid or
				# multi-code request rolls back the whole cart.
				CartPromotions.set_promo_codes(quotation, payload.promo_codes)
				CartLineItems.save(quotation)
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
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
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
			with privileged_scope():
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
			with privileged_scope():
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
			with privileged_scope():
				mapping = CartLineItems.delete(reference, quotation, line_id)
			return reference, quotation, mapping

	def add_promotions(
		self,
		cart_id: str,
		payload: StoreCartAddPromotion,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Apply promotion codes to a locked cart.

		``guard`` is validated against the locked reference before any
		mutation, so a wrong-scoped key never modifies the cart. The Quotation
		saves through ERPNext controllers inside the same locked transaction,
		so an unknown/invalid/multi-code request leaves the cart untouched.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartPromotions.apply(quotation, payload.promo_codes)
				return reference, quotation

	def remove_promotions(
		self,
		cart_id: str,
		payload: StoreCartRemovePromotion,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Remove an applied promotion code from a locked cart.

		``guard`` is validated against the locked reference before any
		mutation (see :meth:`add_promotions`).
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartPromotions.remove(quotation, payload.promo_codes)
				return reference, quotation

	def calculate_taxes(
		self,
		cart_id: str,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Recalculate the locked cart's taxes and totals through ERPNext.

		``guard`` is validated against the locked reference before any
		recalculation (see :meth:`add_promotions`). The numbers are ERPNext's
		own (:meth:`CartTaxes.recalculate`) — the same ones every cart
		response serializes — and a failing save raises inside the locked
		transaction, so the caller's rollback leaves the cart untouched.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartTaxes.recalculate(quotation)
				return reference, quotation

	def set_shipping_method(
		self,
		cart_id: str,
		payload: StoreAddCartShippingMethods,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Resolve ``payload.option_id`` as the locked cart's shipping method.

		``guard`` is validated against the locked reference before any
		mutation (see :meth:`add_promotions`). The save through the ERPNext
		controllers means an unknown, disabled, buying-side, foreign-company
		or country-ineligible option raises before anything is committed.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartShippingMethods.apply(quotation, payload.option_id)
				return reference, quotation

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
		if "promo_codes" in fields:
			# Medusa update semantics: the submitted promo codes replace the
			# cart's codes. The Quotation save below runs the ERPNext
			# pricing-rule controllers for the new coupon state.
			CartPromotions.set_promo_codes(quotation, payload.promo_codes or [])

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
		# ERPNext only loads template rows into an empty taxes table, so the
		# link alone is not enough: CartTaxes refreshes the rows on change.
		CartTaxes.refresh_template(quotation, configuration.taxes_and_charges)
		quotation.territory = configuration.territory

	@staticmethod
	def _validate_currency(requested: str | None, configured: str) -> None:
		if requested and requested.lower() != configured.lower():
			raise InvalidDataError("Cart currency must match the configured price list currency")

	@staticmethod
	def _new_cart_id() -> str:
		return f"cart_{secrets.token_hex(16)}"


@contextmanager
def privileged_scope() -> Iterator[None]:
	"""Run trusted ERPNext controller work as a temporary Administrator.

	The flag alone cannot do this: ERPNext's ``account_perm_check`` resolves
	through ``frappe.has_permission``, which grants only the Administrator
	session user and ignores ``frappe.flags.ignore_permissions``. Both the
	user and the flag are captured and exactly restored in ``finally``, so
	scopes nest safely and leave no elevation behind. Authorization and
	ownership checks must run outside this scope; only trusted persistence
	work belongs inside it.
	"""
	previous_user = frappe.session.user
	previous_flag = frappe.flags.ignore_permissions
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
	frappe.flags.ignore_permissions = True
	try:
		yield
	finally:
		frappe.flags.ignore_permissions = previous_flag
		frappe.set_user(previous_user)  # nosemgrep: frappe-setuser
