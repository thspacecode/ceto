"""Resolve the authenticated cart customer through the shared identity resolver.

Cart ownership flows use the same explicit chain the customers contract
resolves (recorded decision 2 of ``docs/customers/field-mapping.md``): the
enabled Website ``User`` → its ``Contact`` (``Contact.user``) → the one
linked ``Customer``. The resolution rules live in
:cmod:`ceto.services.customers.identity` so carts and customers can never
diverge.
"""

from ceto.services.customers.identity import resolve_customer_identity


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
		return resolve_customer_identity(user).customer
