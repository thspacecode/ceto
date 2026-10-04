"""Identity resolution: the explicit chain behind an authenticated customer.

Pins the resolver contract on the test site: enabled Website User gate, the
explicit User → Contact.user → Customer Dynamic Link path, exactly one
resulting Customer, and unauthorized refusals for zero, partial, ambiguous
and privileged identities.
"""

import uuid

import frappe

from ceto.routing.exceptions import UnauthorizedError
from ceto.services.customers.identity import resolve_customer_identity
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, make_chain, make_customer, new_identity
from ceto.tests.utils import CetoTestSuite

NO_CUSTOMER_MESSAGE = "No customer account is linked to this user"
MULTIPLE_CUSTOMERS_MESSAGE = "User is linked to multiple customers"


class TestCustomerIdentity(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def test_resolves_the_explicit_chain(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, customer, contact = make_chain("resolve")

		identity = resolve_customer_identity(email)

		self.assertEqual(identity.user, email)
		self.assertEqual(identity.contact, contact)
		self.assertEqual(identity.customer, customer)

	def test_resolves_when_the_identity_has_a_second_unlinked_contact(self) -> None:
		# A real registration can end up with Frappe's auto-created Contact
		# plus another contact row (e.g. a portal signup): the Customer stays
		# unambiguous, so the identity still resolves to the linked Contact.
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, customer, contact = make_chain("two-contacts")
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Second",
					"user": email,
				}
			).insert(ignore_permissions=True)

		identity = resolve_customer_identity(email)

		self.assertEqual(identity.customer, customer)
		self.assertEqual(identity.contact, contact)

	def test_masks_missing_identity(self) -> None:
		with self.assertRaises(UnauthorizedError) as raised:
			resolve_customer_identity(f"ceto.missing.{uuid.uuid4().hex}@example.com")

		self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)

	def test_masks_partial_chain(self) -> None:
		# Frappe's auto-created Contact exists, but no Customer is linked:
		# indistinguishable from an unauthenticated request.
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email = new_identity("partial")

		with self.assertRaises(UnauthorizedError) as raised:
			resolve_customer_identity(email)

		self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)

	def test_refuses_multiple_customers(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, _customer, contact = make_chain("multi-customer")
			other = make_customer("multi-customer")
			linked = frappe.get_doc("Contact", contact)
			linked.append("links", {"link_doctype": "Customer", "link_name": other})
			linked.flags.ignore_permissions = True
			linked.save(ignore_permissions=True)

		with self.assertRaises(UnauthorizedError) as raised:
			resolve_customer_identity(email)

		self.assertEqual(str(raised.exception), MULTIPLE_CUSTOMERS_MESSAGE)

	def test_requires_an_enabled_website_user(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, _customer, _contact = make_chain("disabled")
			frappe.db.set_value("User", email, "enabled", 0)

			with self.subTest("disabled user"):
				with self.assertRaises(UnauthorizedError) as raised:
					resolve_customer_identity(email)
				self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)

			system_user = new_identity("system", user_type="System User")
			with self.subTest("system user"):
				with self.assertRaises(UnauthorizedError) as raised:
					resolve_customer_identity(system_user)
				self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)
