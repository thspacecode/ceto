"""Create the ERPNext customer profile behind a registration identity.

The registration auth flow mints only the login User and its single-purpose
token (recorded decision 8 of ``docs/customers/field-mapping.md``); this
service runs later, in the customer-creating request. It first refuses every
identity that must not produce a profile — disabled or privileged accounts,
duplicate owners, ambiguous chains — then creates the explicit Contact →
Customer chain and the ``Ceto Customer Reference`` inside the caller's
transaction.

The registration token is never consumed here: the used-marker lives in cache
and survives database rollbacks, so the route must call
``consume_bearer_registration_token`` only after this transaction has fully
succeeded — a post-success callback at the HTTP boundary, not a step of the
atomic profile creation.
"""

import json
from typing import TYPE_CHECKING, Any

import frappe

from ceto.ceto.doctype.ceto_customer_reference.ceto_customer_reference import mint_customer_id
from ceto.routing.exceptions import UnauthorizedError
from ceto.services.customers.identity import CustomerIdentity, find_identity_chain

if TYPE_CHECKING:
	from frappe.model.document import Document


def create_customer_profile(
	user: str,
	*,
	first_name: str | None = None,
	last_name: str | None = None,
	company_name: str | None = None,
	phone: str | None = None,
	metadata: dict[str, Any] | None = None,
) -> tuple[CustomerIdentity, "Document"]:
	"""Create the one Contact → Customer chain and reference for ``user``.

	``user`` is the registration identity the bearer token attests to; the
	profile columns come from the validated create payload, with the email
	fallback composing ``customer_name`` (recorded decision 2). Returns the
	resolved identity and its reference, whose name is the public ``cus_…``
	id. A Frappe auto-created Contact (``User.on_update`` adds one after a
	registration) is reused; otherwise the Contact is created here with the
	identity's primary email so Frappe's own contact job converges on it
	instead of inserting a second Contact for the identity.

	Raises :class:`UnauthorizedError` — before any privileged write — when
	the identity is not an enabled Website User, already owns a Customer
	(duplicate create or pre-existing account), or is ambiguous (several
	Contacts, several Customers). A lost insert race on the reference's
	unique Customer/User indexes converges onto the same refusal: the caller
	rolls the transaction back, so no partial second profile can survive.
	"""
	contacts, customers = find_identity_chain(user)
	if customers:
		raise UnauthorizedError("User already owns a customer account")
	if len(contacts) > 1:
		raise UnauthorizedError("User is linked to multiple contacts")

	def insert_customer() -> "Document":
		customer = frappe.new_doc("Customer")
		customer.customer_type = "Individual"
		customer.customer_name = " ".join(part for part in (first_name, last_name) if part) or user
		customer.customer_group = default_customer_group()
		customer.territory = "All Territories"
		customer.flags.ignore_permissions = True
		customer.insert()
		return customer

	def default_customer_group() -> str | None:
		group = frappe.db.get_single_value("Selling Settings", "customer_group")
		return group or frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name")

	def link_contact(customer_name: str) -> str:
		contact = (
			frappe.get_doc("Contact", contacts[0])
			if contacts
			else new_contact(frappe.db.get_value("User", user, "first_name"))
		)
		contact.user = user
		if first_name:
			contact.first_name = first_name
		if last_name:
			contact.last_name = last_name
		if company_name is not None:
			contact.company_name = company_name
		if phone:
			contact.add_phone(phone, is_primary_phone=True)
		ensure_identity_email(contact)
		if not contact.has_link("Customer", customer_name):
			contact.append("links", {"link_doctype": "Customer", "link_name": customer_name})
		contact.flags.ignore_permissions = True
		if contacts:
			contact.save(ignore_permissions=True)
		else:
			contact.insert(ignore_permissions=True)
		return contact.name

	def new_contact(fallback_first_name: str | None) -> "Document":
		contact = frappe.new_doc("Contact")
		contact.first_name = first_name or fallback_first_name
		contact.last_name = last_name
		return contact

	def ensure_identity_email(contact: "Document") -> None:
		"""Add the identity's email so Frappe's contact job converges on this Contact.

		The email row is what the post-registration job matches on; a second
		primary would be rejected by the Contact controller, so the identity
		email only claims the primary slot when no other email has it.
		"""
		primary_taken = any(row.is_primary for row in (contact.get("email_ids") or []))
		contact.add_email(user, is_primary=not primary_taken)

	def insert_reference(customer_name: str) -> "Document":
		reference = frappe.new_doc("Ceto Customer Reference")
		reference.customer_id = mint_customer_id()
		reference.customer = customer_name
		reference.user = user
		reference.metadata = json.dumps(metadata, separators=(",", ":"), sort_keys=True) if metadata else None
		try:
			reference.insert(ignore_permissions=True)
		except frappe.UniqueValidationError:
			# A concurrent create bound the identity first; converge on the
			# same refusal as the pre-check above.
			raise UnauthorizedError("User already owns a customer account") from None
		return reference

	customer = insert_customer()
	contact = link_contact(customer.name)
	reference = insert_reference(customer.name)
	return CustomerIdentity(user=user, contact=contact, customer=customer.name), reference
