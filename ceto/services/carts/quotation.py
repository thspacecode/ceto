import json
import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import getdate, today

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.configuration import CartConfiguration
from ceto.types.http.store.carts import StoreCreateCart, StoreUpdateCart

if TYPE_CHECKING:
	from frappe.model.document import Document


class CartService:
	def __init__(self, access: CartAccess | None = None) -> None:
		self.access = access or CartAccess()

	def create(self, payload: StoreCreateCart) -> tuple["Document", "Document"]:
		self._reject_deferred_create_fields(payload)
		configuration = CartConfiguration.resolve(
			region_id=payload.region_id,
			sales_channel_id=payload.sales_channel_id,
		)
		self._validate_currency(payload.currency_code, configuration.currency)

		owner_user = self.access.owner_user()
		with _as_administrator():
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
					"metadata": self._dump_metadata(payload.metadata),
				}
			).insert(ignore_permissions=True)
		return reference, quotation

	def retrieve(self, cart_id: str) -> tuple["Document", "Document"]:
		return self.access.get(cart_id)

	def update(self, cart_id: str, payload: StoreUpdateCart) -> tuple["Document", "Document"]:
		self._reject_deferred_update_fields(payload)
		with self.access.lock(cart_id) as (reference, quotation):
			self._apply_update(reference, quotation, payload)
			with _as_administrator():
				quotation.flags.ignore_mandatory = True
				quotation.save(ignore_permissions=True)
				reference.save(ignore_permissions=True)
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
			reference.metadata = self._updated_metadata(reference.metadata, payload.metadata)

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
		# Medusa creates carts before they have lines. ERPNext's mandatory child
		# table check is deferred until Phase 2 adds the first Quotation Item.
		quotation.flags.ignore_mandatory = True
		return quotation.insert(ignore_permissions=True)

	@staticmethod
	def _apply_configuration(quotation: "Document", configuration: CartConfiguration) -> None:
		quotation.company = configuration.company
		quotation.currency = configuration.currency
		quotation.selling_price_list = configuration.selling_price_list
		quotation.territory = configuration.territory

	@staticmethod
	def _validate_currency(requested: str | None, configured: str) -> None:
		if requested and requested.lower() != configured.lower():
			raise InvalidDataError("Cart currency must match the configured price list currency")

	@staticmethod
	def _reject_deferred_create_fields(payload: StoreCreateCart) -> None:
		if payload.shipping_address is not None or payload.billing_address is not None:
			raise InvalidDataError("Cart addresses are not supported yet")
		if payload.items:
			raise InvalidDataError("Cart line items are not supported yet")
		if payload.promo_codes:
			raise InvalidDataError("Cart promotions are not supported yet")

	@staticmethod
	def _reject_deferred_update_fields(payload: StoreUpdateCart) -> None:
		if payload.shipping_address is not None or payload.billing_address is not None:
			raise InvalidDataError("Cart addresses are not supported yet")
		if payload.promo_codes:
			raise InvalidDataError("Cart promotions are not supported yet")

	@staticmethod
	def _new_cart_id() -> str:
		return f"cart_{secrets.token_hex(16)}"

	@staticmethod
	def _dump_metadata(metadata: dict[str, Any] | None) -> str | None:
		return json.dumps(metadata, separators=(",", ":"), sort_keys=True) if metadata else None

	@classmethod
	def _updated_metadata(cls, current: str | None, update: dict[str, Any] | None) -> str | None:
		if update is None:
			return None
		metadata = json.loads(current) if current else {}
		for key, value in update.items():
			if value is None:
				metadata.pop(key, None)
			else:
				metadata[key] = value
		return cls._dump_metadata(metadata)


@contextmanager
def _as_administrator():
	"""Run trusted ERPNext controller work with account read access."""
	user = frappe.session.user
	try:
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
		yield
	finally:
		frappe.set_user(user)  # nosemgrep: frappe-setuser
