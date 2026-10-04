import secrets
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

import frappe
from erpnext.controllers.accounts_controller import get_taxes_and_charges
from frappe.utils import getdate, today

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError, UnauthorizedError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.addresses import CartAddresses
from ceto.services.carts.configuration import CartConfiguration
from ceto.services.carts.credits import CartCredits
from ceto.services.carts.customers import CartCustomers
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.promotions import CartPromotions
from ceto.services.carts.shipping import CartShippingMethods
from ceto.services.carts.taxes import CartTaxes
from ceto.services.common import dump_metadata, merged_metadata, privileged_scope
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreAddGiftCardToCart,
	StoreAddStoreCreditsToCart,
	StoreCartAddPromotion,
	StoreCartRemovePromotion,
	StoreCreateCart,
	StoreRemoveGiftCardFromCart,
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
				# A template reload or channel re-price shrinks the payable; unbook first.
				CartCredits.stage_for_mutation(quotation)
				self._apply_update(reference, quotation, payload)
				self.addresses.apply(reference, quotation, payload)
				# Shared save helper: keeps the mandatory-items relaxation only
				# while the cart is empty and recomputes totals otherwise.
				CartLineItems.save(quotation)
				self.addresses.enforce_cleared(quotation, payload)
				# A template reload or promo/price change moves the totals;
				# the credit holds are re-capped and their deduction rows
				# rewritten before the cart is returned.
				CartCredits.reconcile(quotation)
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
				CartCredits.reconcile(quotation)
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
				# A quantity decrease shrinks the payable; unbook first.
				CartCredits.stage_for_mutation(quotation)
				mapping = CartLineItems.update(reference, quotation, line_id, payload)
				CartCredits.reconcile(quotation)
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
				# Removing lines shrinks what the holds can absorb; unbook first.
				CartCredits.stage_for_mutation(quotation)
				mapping = CartLineItems.delete(reference, quotation, line_id)
				CartCredits.reconcile(quotation)
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
				# A discount shrinks the payable below the booked deduction; unbook first.
				CartCredits.stage_for_mutation(quotation)
				CartPromotions.apply(quotation, payload.promo_codes)
				# Discount changes move the totals; holds are re-capped.
				CartCredits.reconcile(quotation)
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
				# Discount changes move the totals; holds are re-capped.
				CartCredits.reconcile(quotation)
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
				# A cheaper template rate shrinks the payable; unbook first.
				CartCredits.stage_for_mutation(quotation)
				CartTaxes.recalculate(quotation)
				# The recalculation rebuilt the totals (and possibly the
				# taxes table); the holds and their deduction rows follow.
				CartCredits.reconcile(quotation)
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
				# A cheaper replacement charge shrinks the payable; unbook first.
				CartCredits.stage_for_mutation(quotation)
				CartShippingMethods.apply(quotation, payload.option_id)
				# The shipping charge moves the totals; holds are re-capped.
				CartCredits.reconcile(quotation)
				return reference, quotation

	def add_gift_card(
		self,
		cart_id: str,
		payload: StoreAddGiftCardToCart,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Apply a gift card to the locked cart.

		``guard`` is validated against the locked reference before any
		mutation, so a wrong-scoped key never modifies the cart (see
		:meth:`add_promotions`). The wallet row is locked inside the cart
		lock before its balance is read, so concurrent applications of one
		card serialize; a failing resolution (unknown code, wrong currency,
		expired or exhausted card, no amount payable) raises inside the
		locked transaction and the caller's rollback leaves the cart
		untouched.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartCredits.apply_gift_card(quotation, payload.code)
				return reference, quotation

	def remove_gift_card(
		self,
		cart_id: str,
		payload: StoreRemoveGiftCardFromCart,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Release the gift card applied to the locked cart.

		``guard`` is validated against the locked reference before any
		mutation (see :meth:`add_promotions`). The pinned removal is
		bodyful: ``payload.code`` selects the released hold by code hash.
		"""
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			with privileged_scope():
				CartCredits.remove_gift_card(quotation, payload.code)
				return reference, quotation

	def add_store_credits(
		self,
		cart_id: str,
		payload: StoreAddStoreCreditsToCart,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Reserve the authenticated customer's store credit on the locked cart.

		The loyalty plugin's middleware authenticates the customer for this
		route, so an anonymous request fails as ``401 unauthorized`` before
		the cart is locked — as does a session user without a Customer
		linked through its Contact (same resolver as the claim). The hold
		is booked against that customer's wallet for the cart's company and
		currency; reapplying replaces the cart's prior reservation(s). A
		cart owned by another authenticated user is rejected as
		``not_found`` before the ledger is touched.
		"""
		user = CartAccess.owner_user()
		if not user:
			raise UnauthorizedError("Store credits require an authenticated customer")
		customer = CartCustomers().resolve(user)
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			if reference.owner_user and reference.owner_user != user:
				# A customer wallet is never applied to a cart owned by
				# another authenticated user. ``CartAccess`` already masks
				# foreign carts on every route; this restates the invariant
				# at the money-moving boundary so it holds even if a future
				# caller reaches past the access helper, and it masks the
				# same way (``not_found``) instead of leaking existence.
				raise RouteNotFoundError("Cart not found")
			with privileged_scope():
				CartCredits.apply_store_credits(quotation, customer, payload.amount)
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
