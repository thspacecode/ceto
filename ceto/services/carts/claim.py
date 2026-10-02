"""Authenticated customer claim (Medusa ``transferCart``) for Ceto carts.

Claiming moves a guest cart to the authenticated Frappe user's ERPNext
Customer inside the cart row lock:

- Requires an authenticated session; the session user must resolve to a
  Customer through its Contact (``CartCustomers``).
- The guest party, contact and address context is replaced: cart-scoped
  temporary addresses are copied to the claiming Customer, the cart is
  relinked to those copies, and the temporary records are deleted. Addresses
  that already belong to the claiming Customer stay linked.
- Item pricing is re-fetched by ERPNext for the new party (pricing rules,
  taxes) and all totals are recalculated by the controller; the
  sales-channel price list itself is part of the cart configuration and is
  never re-inferred from the claiming Customer.
- Claiming again as the same user is idempotent and causes no mutation.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from ceto.routing.exceptions import UnauthorizedError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.addresses import CartAddresses
from ceto.services.carts.customers import CartCustomers
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.quotation import privileged_scope

if TYPE_CHECKING:
	from frappe.model.document import Document


class CartClaim:
	"""Claim a guest cart for the authenticated session user's Customer."""

	def __init__(
		self,
		access: CartAccess | None = None,
		addresses: CartAddresses | None = None,
		customers: CartCustomers | None = None,
	) -> None:
		self.access = access or CartAccess()
		self.addresses = addresses or CartAddresses()
		self.customers = customers or CartCustomers()

	def claim(
		self,
		cart_id: str,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> tuple["Document", "Document"]:
		"""Claim ``cart_id`` for the session user; returns (reference, quotation).

		``guard`` runs against the row-locked reference before any mutation,
		matching the lock order of the other cart mutations (no TOCTOU).
		Carts owned by a different user are masked as ``404 not_found`` by
		``CartAccess.lock``.
		"""
		user = CartAccess.owner_user()
		if not user:
			raise UnauthorizedError("Cart customer claim requires an authenticated session")
		customer = self.customers.resolve(user)
		with self.access.lock(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			if reference.owner_user == user and reference.owner_customer == customer:
				# Idempotent: already claimed by this user's customer.
				return reference, quotation
			with privileged_scope():
				self._apply(reference, quotation, user, customer)
			return reference, quotation

	def _apply(
		self,
		reference: "Document",
		quotation: "Document",
		user: str,
		customer: str,
	) -> None:
		self.addresses.attach_owner(quotation, customer)
		quotation.party_name = customer
		quotation.contact_person = None
		quotation.contact_display = None
		quotation.contact_email = user
		self._reset_item_pricing(quotation)
		# Controller save re-runs pricing (pricing rules for the new
		# customer), taxes and every document total. The sales-channel price
		# list is part of the cart's configuration, never of its party
		# (Recorded Decision 1), so it is captured before the save and
		# restored afterwards in case ERPNext's party-details fetch ever
		# replaces it with the claiming Customer's default price list.
		channel_pricing = {
			field: quotation.get(field)
			for field in (
				"selling_price_list",
				"price_list_currency",
				"currency",
				"conversion_rate",
				"plc_conversion_rate",
			)
		}
		CartLineItems.save(quotation)
		for field, value in channel_pricing.items():
			if quotation.get(field) != value:
				quotation.db_set(field, value, notify=False)
		reference.owner_user = user
		reference.owner_customer = customer
		reference.save(ignore_permissions=True)

	@staticmethod
	def _reset_item_pricing(quotation: "Document") -> None:
		"""Clear stored guest rates so ERPNext re-fetches them for the customer.

		``set_missing_item_details`` only refills missing values, so the guest
		party's ``price_list_rate`` / ``rate`` / discount fields are reset to
		``None`` before the save; nothing is ever derived by Ceto itself.
		"""
		for row in quotation.items:
			row.price_list_rate = None
			row.rate = None
			row.discount_percentage = None
			row.discount_amount = None
