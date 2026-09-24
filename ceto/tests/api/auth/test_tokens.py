import frappe

from ceto.api.auth.tokens import refresh_authentication_token
from ceto.services.auth.tokens import create_customer_token, decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER, TEST_SYSTEM_USER
from ceto.tests.utils import CetoTestSuite


class TestTokenRefresh(CetoTestSuite):
	def test_refreshes_token_for_website_customer(self):
		original = create_customer_token(TEST_CUSTOMER)
		with self.set_user(TEST_CUSTOMER):
			response = refresh_authentication_token()

		self.assertNotEqual(response.token, original)
		self.assertEqual(decode_customer_token(response.token)["sub"], TEST_CUSTOMER)

	def test_rejects_system_user(self):
		with self.set_user(TEST_SYSTEM_USER), self.assertRaises(frappe.AuthenticationError):
			refresh_authentication_token()
