"""Cart customer resolver regression through the shared identity resolver.

``CartCustomers`` now delegates to ``ceto.services.customers.identity``; these
tests pin the ownership behaviour the cart claim and store-credit flows rely
on — the same messages the routes have always returned, unchanged by the
refactor.
"""

import frappe

from ceto.routing.exceptions import UnauthorizedError
from ceto.services.carts.customers import CartCustomers
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, make_chain, make_customer, new_identity
from ceto.tests.utils import CetoTestSuite

NO_CUSTOMER_MESSAGE = "No customer account is linked to this user"
MULTIPLE_CUSTOMERS_MESSAGE = "User is linked to multiple customers"


class TestCartCustomersResolver(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def test_resolves_the_customer_for_a_cart_owner(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, customer, _contact = make_chain("cart-resolve")

		self.assertEqual(CartCustomers.resolve(email), customer)

	def test_masks_a_user_without_a_customer_as_unauthorized(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email = new_identity("cart-partial")

		with self.assertRaises(UnauthorizedError) as raised:
			CartCustomers.resolve(email)

		self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)

	def test_refuses_multiple_customers(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, _customer, contact = make_chain("cart-multi")
			linked = frappe.get_doc("Contact", contact)
			linked.append("links", {"link_doctype": "Customer", "link_name": make_customer("cart-multi")})
			linked.flags.ignore_permissions = True
			linked.save(ignore_permissions=True)

		with self.assertRaises(UnauthorizedError) as raised:
			CartCustomers.resolve(email)

		self.assertEqual(str(raised.exception), MULTIPLE_CUSTOMERS_MESSAGE)

	def test_requires_an_enabled_website_user(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email, _customer, _contact = make_chain("cart-disabled")
			frappe.db.set_value("User", email, "enabled", 0)

		with self.assertRaises(UnauthorizedError) as raised:
			CartCustomers.resolve(email)

		self.assertEqual(str(raised.exception), NO_CUSTOMER_MESSAGE)
