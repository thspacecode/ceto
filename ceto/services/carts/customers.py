"""Resolve the authenticated Frappe user to the owning ERPNext Customer.

Follows the recorded Phase 0 decision (``docs/carts/field-mapping.md``):
Frappe ``User`` → ``Contact`` (``Contact.user``) → ``Customer`` via a
Dynamic Link. No other inference (e.g. email matching) is performed so a
Customer is only ever attached to a cart through an explicit, existing link
created at signup.
"""

import frappe

from ceto.routing.exceptions import UnauthorizedError


class CartCustomers:
	"""Narrow Frappe-User → Customer resolver for cart ownership flows."""

	@staticmethod
	def resolve(user: str) -> str:
		"""Return the Customer linked to ``user`` via its Contact.

		Raises :class:`UnauthorizedError` when the user has no Customer, which
		keeps the claim endpoint's failure mode identical to an unauthenticated
		request (Medusa returns ``unauthorized`` for a missing customer token).
		Multiple distinct linked Customers are ambiguous — they cannot be
		resolved deterministically to a single cart owner — and are rejected
		the same way instead of picking one silently.
		"""
		contacts = frappe.get_all("Contact", filters={"user": user}, pluck="name")
		customers = set()
		if contacts:
			customers = set(
				frappe.get_all(
					"Dynamic Link",
					filters={
						"parenttype": "Contact",
						"parent": ["in", contacts],
						"link_doctype": "Customer",
					},
					pluck="link_name",
				)
			)
		if len(customers) == 1:
			return customers.pop()
		if len(customers) > 1:
			raise UnauthorizedError("User is linked to multiple customers")
		raise UnauthorizedError("No customer account is linked to this user")
