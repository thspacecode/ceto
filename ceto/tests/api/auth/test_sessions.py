import frappe
from frappe.auth import LoginManager
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.api.auth.sessions import create_authentication_session, delete_authentication_session
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER
from ceto.tests.utils import CetoTestSuite


class TestAuthSessions(CetoTestSuite):
	def test_creates_and_deletes_customer_session(self):
		request = Request(
			EnvironBuilder(
				path="/ceto/auth/session",
				method="POST",
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			).get_environ()
		)
		manager = self._login_manager()
		previous_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = manager
		try:
			with self.set_user(TEST_CUSTOMER), self.set_request(request):
				response = create_authentication_session()
				self.assertEqual(response.user.id, TEST_CUSTOMER)
				self.assertEqual(response.user.email, TEST_CUSTOMER)
				self.assertTrue(frappe.session.sid)
				self.assertEqual(frappe.session.user, TEST_CUSTOMER)

				deleted = delete_authentication_session()
				self.assertTrue(deleted.success)
				self.assertEqual(frappe.session.user, "Guest")
		finally:
			frappe.local.login_manager = previous_manager

	@staticmethod
	def _login_manager() -> LoginManager:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		return manager
