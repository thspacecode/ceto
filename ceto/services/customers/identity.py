"""Resolve a Frappe login identity to its one ERPNext Customer.

The explicit identity chain is recorded decision 2 of
``docs/customers/field-mapping.md``: the enabled Website ``User`` named by the
registered email owns a ``Contact`` (``Contact.user``) whose Dynamic Link names
the one ``Customer``. No other inference (e.g. email matching) is performed, so
a Customer is only ever reached through an explicit, existing link. The same
resolution backs the cart ownership flows and the customers contract.
"""

from dataclasses import dataclass

import frappe

from ceto.routing.exceptions import UnauthorizedError


@dataclass(frozen=True)
class CustomerIdentity:
	"""The explicit identity chain of one store customer.

	``user`` is the enabled Website User (the login identity and the public
	email), ``contact`` the Contact carrying the profile columns, and
	``customer`` the selling party carts and orders reference.
	"""

	user: str
	contact: str
	customer: str


def find_identity_chain(user: str) -> tuple[list[str], set[str]]:
	"""Return the (contacts, linked customers) behind a registration identity.

	The identity must be an enabled Website User — the login identity the
	registration flow mints; anything else is refused as unauthorized, so a
	disabled or privileged account can never pass for a store customer.
	"""
	user_details = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not user_details or not user_details.enabled or user_details.user_type != "Website User":
		raise UnauthorizedError("No customer account is linked to this user")
	contacts = frappe.get_all("Contact", filters={"user": user}, pluck="name")
	customers: set[str] = set()
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
	return contacts, customers


def resolve_customer_identity(user: str) -> CustomerIdentity:
	"""Resolve an authenticated user to the one Customer its chain links.

	Exactly one resulting Customer resolves; zero contacts, a partial chain
	(a Contact without its Customer) and several Customers are refused as
	unauthorized — the same failure mode as an unauthenticated request, so a
	response can never confirm which identities exist. The resolved Contact
	is the one carrying the Customer Dynamic Link.
	"""
	contacts, customers = find_identity_chain(user)
	if len(customers) > 1:
		raise UnauthorizedError("User is linked to multiple customers")
	if not customers:
		# No Contact at all, or a partial chain (a Contact without its
		# Customer): masked exactly like an unauthenticated request.
		raise UnauthorizedError("No customer account is linked to this user")
	customer = customers.pop()
	contact = frappe.db.get_value(
		"Dynamic Link",
		{
			"parenttype": "Contact",
			"parent": ["in", contacts],
			"link_doctype": "Customer",
			"link_name": customer,
		},
		"parent",
		order_by="creation asc",
	)
	return CustomerIdentity(user=user, contact=contact, customer=customer)
