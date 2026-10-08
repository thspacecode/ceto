"""Resolve a Frappe login identity to its one ERPNext Customer.

The explicit identity chain is recorded decision 2 of
``docs/customers/field-mapping.md``: the enabled Website ``User`` named by the
registered email owns a ``Contact`` (``Contact.user``) whose Dynamic Link names
the one ``Customer``. No other inference (e.g. email matching) is performed, so
a Customer is only ever reached through an explicit, existing link. The same
resolution backs the cart ownership flows and the customers contract.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import frappe

from ceto.routing.exceptions import UnauthorizedError

if TYPE_CHECKING:
	from frappe.model.document import Document


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


def resolve_customer_reference(user: str) -> tuple[CustomerIdentity, "Document"]:
	"""Resolve an authenticated user to its identity chain and public reference.

	The ``Ceto Customer Reference`` is part of the contract identity
	(recorded decision 1): a chain that resolves without one — a pre-existing
	ERPNext account linked outside Ceto — has no contract-safe public id, so
	it is masked exactly like the other unresolvable identities instead of
	leaking that the account exists. Defense in depth at read time: the
	reference found by user must also name the chain's own Customer; a row
	that drifted away from the chain is refused exactly the same way.
	"""
	identity = resolve_customer_identity(user)
	reference_name = frappe.db.get_value("Ceto Customer Reference", {"user": identity.user})
	if not reference_name:
		raise UnauthorizedError("No customer account is linked to this user")
	reference = frappe.get_doc("Ceto Customer Reference", reference_name)
	if reference.customer != identity.customer:
		# The write-time validate pins a reference to the chain's Customer;
		# only drift outside the ORM can detach them, and this identity must
		# not bless it — masked like every other unresolvable identity.
		raise UnauthorizedError("No customer account is linked to this user")
	return identity, reference


def find_customer_reference(user: str) -> tuple[CustomerIdentity, "Document"] | None:
	"""Resolve ``user`` to its identity chain and reference, or ``None``.

	The quiet twin of :func:`resolve_customer_reference` for read paths that
	must render without an identity — the order serializer embeds the
	completed cart's owner only when a resolvable customer exists. Every
	refusal the strict resolver raises (no chain, no Customer, no reference,
	a drifted reference) resolves to ``None`` here, so the read surface can
	never disagree with the customers contract about who owns a public
	``cus_…`` id, and no identity is ever invented for the gaps.
	"""
	try:
		return resolve_customer_reference(user)
	except UnauthorizedError:
		return None
