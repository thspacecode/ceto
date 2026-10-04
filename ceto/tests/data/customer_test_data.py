"""Fixtures for the customers identity/data-model tests.

The identity chains mirror what the store really produces: the registration
flow mints the User (Frappe auto-creates its Contact — ``Contact.user`` plus
the primary email row — in the same transaction under test) and the profile
creation links that Contact to the one Customer. Records stay uncommitted
like every integration fixture; each test rolls back.
"""

import uuid

import frappe

THROTTLE_USER_LIMIT = 100000


def new_identity(label: str, *, user_type: str = "Website User") -> str:
	"""Mint a login User like the registration flow; return its email."""
	email = f"ceto.customers.{label}.{uuid.uuid4().hex[:8]}@example.com"
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": f"Customers {label}",
			"user_type": user_type,
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	return email


def make_customer(label: str) -> str:
	"""Create an Individual Customer the way the profile service does."""
	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": f"Customers {label} {uuid.uuid4().hex[:8]}",
			"customer_type": "Individual",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="name"),
			"territory": "All Territories",
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()
	return customer.name


def link_customer(email: str, customer: str) -> str:
	"""Attach the Customer Dynamic Link to the identity's Contact; return its name."""
	contact_name = frappe.db.get_value("Contact", {"user": email})
	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
	else:
		contact = frappe.new_doc("Contact")
		contact.first_name = frappe.db.get_value("User", email, "first_name")
		contact.user = email
	contact.add_email(email, is_primary=True)
	contact.append("links", {"link_doctype": "Customer", "link_name": customer})
	contact.flags.ignore_permissions = True
	if contact_name:
		contact.save(ignore_permissions=True)
	else:
		contact.insert(ignore_permissions=True)
	return contact.name


def make_chain(label: str) -> tuple[str, str, str]:
	"""Mint the full explicit identity chain; returns (email, customer, contact)."""
	email = new_identity(label)
	customer = make_customer(label)
	contact = link_customer(email, customer)
	return email, customer, contact
