import frappe
from frappe.auth import LoginManager
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.api.auth.authentication import authenticate, authenticate_callback
from ceto.routing import JSON
from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.auth import AuthResponse


class TestAuthentication(CetoTestSuite):
	def test_endpoints_are_not_whitelisted(self):
		self.assertNotIn(authenticate, frappe.whitelisted)
		self.assertNotIn(authenticate_callback, frappe.whitelisted)
		self.assertFalse(hasattr(authenticate, "is_whitelisted"))
		self.assertFalse(hasattr(authenticate_callback, "is_whitelisted"))

	def test_authenticate_uses_real_website_user(self):
		request = self._request("/ceto/auth/customer/emailpass", "POST")
		login_manager = self._login_manager()
		previous_login_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = login_manager
		try:
			with self.set_request(request):
				response = authenticate("emailpass", email=TEST_CUSTOMER, password=TEST_CUSTOMER_PASSWORD)
		finally:
			frappe.local.login_manager = previous_login_manager

		self.assertIsInstance(response, JSON)
		self.assertIsInstance(response.value, AuthResponse)
		self.assertEqual(decode_customer_token(response.value.token)["sub"], TEST_CUSTOMER)
		self.assertEqual(login_manager.user, TEST_CUSTOMER)

	@staticmethod
	def _login_manager() -> LoginManager:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		return manager

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())
