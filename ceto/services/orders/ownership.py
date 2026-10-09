"""Effective ownership of a placed order (the Medusa ``customer_id``).

The order reference carries the owner: the completing transaction snapshots
the cart's ``owner_customer`` onto the ``Ceto Order Reference`` inside the
settle, so the order's owner is fixed at birth and never re-derived (orders
field-mapping Recorded Decision 2). The completed cart's ownership is
immutable — a cart leaves every cart route once its Quotation is submitted —
so the snapshot and the fallback below always agree for records born with
the column.

Legacy references completed before the column existed carry only
``{order_id, sales_order, cart_id}``; they resolve their effective owner
from the completed cart's ``Ceto Cart Reference.owner_customer`` — the same
Customer the Frappe ``User`` → ``Contact`` → ``Customer`` chain resolved at
claim/completion time (carts Recorded Decision 3) — and the backfill patch
copies that value onto the reference once. The cart history is only ever a
fallback, never the live source.

Deliberate boundaries: a guest order has no owner (``None`` — the
unguessable ``order_…`` id is its capability, Recorded Decision 4), the
Sales Order's own customer links are never ownership evidence (a guest
checkout's Sales Order names the configured Guest Customer), and this
module never writes — the one-time backfill is the patch's job.
"""

from typing import TYPE_CHECKING

import frappe

if TYPE_CHECKING:
	from frappe.model.document import Document


class OrderOwnership:
	"""Resolve an order reference's effective owner."""

	@staticmethod
	def effective_owner(order_reference: "Document") -> str | None:
		"""Return the reference's effective owner, or ``None`` for a guest order.

		The ``owner_customer`` snapshot is the live source. A reference
		without one (a Phase 6 legacy row) falls back to the completed
		cart's owner; a guest order falls through to ``None`` on both, and
		a dangling cart reference degrades to ``None`` instead of raising.
		"""
		snapshot = order_reference.get("owner_customer")
		if snapshot:
			return snapshot
		return (
			frappe.db.get_value("Ceto Cart Reference", order_reference.get("cart_id"), "owner_customer")
			or None
		)
