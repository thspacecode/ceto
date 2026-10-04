"""Secure resolution of placed orders: a public id becomes its records.

The Store retrieve surface is capability-based (orders Recorded Decision 4):
no customer authentication — the unguessable ``order_…`` id is the
credential. Two gates, and every maskable failure raises the same
``404 not_found``:

- **Lineage**: the reference must still stand for its completed cart
  reference (Quotation submitted) and its submitted Sales Order — re-checked
  here so state broken after the fact is masked like an unknown id, never a
  ``500``.
- **Publishable-key scope** (Recorded Decision 5): the order inherits the
  completed cart's region / sales channel and the presented key must match.
  The comparison carts refuse with ``not_allowed`` is masked here: on a
  read-only surface a foreign order simply does not exist for that key.

Ownership is never a gate (Recorded Decisions 2 and 4); the Sales Order's
name stays internal (Recorded Decision 1) — it reaches the serializer,
never a response.
"""

from typing import TYPE_CHECKING, Protocol

import frappe
from frappe.utils import cint

from ceto.routing.exceptions import RouteNotFoundError

if TYPE_CHECKING:
	from frappe.model.document import Document

#: The one safe failure: every maskable case raises exactly this, so the
#: cases stay indistinguishable.
ORDER_NOT_FOUND = "Order not found"


class PublishableKeyScope(Protocol):
	"""Structural view of a publishable key's scope (services never import ``ceto.api``)."""

	region_id: str | None
	sales_channel_id: str | None


class OrderAccess:
	"""Resolve a public ``order_…`` id into its placed-order records."""

	def resolve(
		self,
		order_id: str,
		key: PublishableKeyScope,
	) -> tuple["Document", "Document", "Document"]:
		"""Return ``(order_reference, sales_order, cart_reference)``.

		``key`` is the publishable key the caller resolved as every Store
		route does (``CartPublishableKey.from_request``); its scope is
		enforced before the Sales Order is loaded.
		"""
		order_reference = self._order_reference(order_id)
		reference = self._completed_cart(order_reference)
		self._check_scope(key, reference)
		sales_order = self._sales_order(order_reference)
		return order_reference, sales_order, reference

	@staticmethod
	def _order_reference(order_id: str) -> "Document":
		try:
			return frappe.get_doc("Ceto Order Reference", order_id)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError(ORDER_NOT_FOUND)

	@staticmethod
	def _completed_cart(order_reference: "Document") -> "Document":
		"""Load the completed cart context; mask broken lineage.

		The reference carries the order's inherited scope; its Quotation
		being submitted is the pinned "actually completed" invariant.
		"""
		try:
			reference = frappe.get_doc("Ceto Cart Reference", order_reference.cart_id)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError(ORDER_NOT_FOUND)
		if cint(frappe.db.get_value("Quotation", reference.quotation, "docstatus")) != 1:
			raise RouteNotFoundError(ORDER_NOT_FOUND)
		return reference

	@staticmethod
	def _sales_order(order_reference: "Document") -> "Document":
		"""Load the submitted ERPNext Sales Order the reference books."""
		try:
			sales_order = frappe.get_doc("Sales Order", order_reference.sales_order)
		except frappe.DoesNotExistError:
			raise RouteNotFoundError(ORDER_NOT_FOUND)
		if sales_order.docstatus != 1:
			# The reference books a *submitted* Sales Order; un-submitted is broken state.
			raise RouteNotFoundError(ORDER_NOT_FOUND)
		return sales_order

	@staticmethod
	def _check_scope(key: PublishableKeyScope, reference: "Document") -> None:
		"""Mask a wrong-scoped key as ``not_found`` (Recorded Decision 5).

		Same comparison ``CartPublishableKey.check_values`` applies to
		carts — only a constraining key and a differently-scoped reference
		mismatch — but masked, so a wrong-scoped key cannot tell a
		foreign order from a missing one.
		"""
		if key.region_id and reference.region_id and reference.region_id != key.region_id:
			raise RouteNotFoundError(ORDER_NOT_FOUND)
		if (
			key.sales_channel_id
			and reference.sales_channel_id
			and reference.sales_channel_id != key.sales_channel_id
		):
			raise RouteNotFoundError(ORDER_NOT_FOUND)
