import frappe
from frappe.auth import LoginManager
from frappe.utils.password import check_password
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.services.auth.providers.emailpass import EmailPasswordProvider
from ceto.services.auth.registration import create_registration_identity
from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER_PASSWORD
from ceto.tests.utils import CetoTestSuite


class TestRegistration(CetoTestSuite):
	def test_identity_stores_hashed_password(self):
		email = self._new_email()
		with self.set_conf(throttle_user_limit=100000):
			name = create_registration_identity(email, TEST_CUSTOMER_PASSWORD)

		self.assertEqual(name, email.lower())
		auth = frappe.db.get_value(
			"__Auth",
			{"doctype": "User", "name": name, "fieldname": "password"},
			["password", "encrypted"],
			as_dict=True,
			order_by="",
		)
		self.assertIsNotNone(auth)
		self.assertNotEqual(auth.password, TEST_CUSTOMER_PASSWORD)
		self.assertFalse(auth.encrypted)
		self.assertFalse(frappe.db.get_value("User", name, "new_password"))
		check_password(name, TEST_CUSTOMER_PASSWORD)

	def test_identity_authenticates_through_emailpass(self):
		email = self._new_email()
		with self.set_conf(throttle_user_limit=100000):
			create_registration_identity(email, TEST_CUSTOMER_PASSWORD)

		token = self._authenticate(email, TEST_CUSTOMER_PASSWORD)

		self.assertEqual(decode_customer_token(token)["sub"], email.lower())

	def test_identity_rejects_wrong_password(self):
		email = self._new_email()
		with self.set_conf(throttle_user_limit=100000):
			create_registration_identity(email, TEST_CUSTOMER_PASSWORD)

		with self.assertRaises(frappe.AuthenticationError):
			self._authenticate(email, "Not the registered password 42!")

	def test_identity_and_password_rollback_together(self):
		email = self._new_email()
		with self.set_conf(throttle_user_limit=100000):
			create_registration_identity(email, TEST_CUSTOMER_PASSWORD)

		check_password(email, TEST_CUSTOMER_PASSWORD)
		frappe.db.rollback()

		self.assertFalse(frappe.db.exists("User", email.lower()))
		self.assertFalse(
			frappe.db.get_value(
				"__Auth",
				{"doctype": "User", "name": email.lower(), "fieldname": "password"},
				order_by="",
			)
		)

	def _authenticate(self, email: str, password: str) -> str:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		request = Request(
			EnvironBuilder(
				"/ceto/auth/customer/emailpass",
				"POST",
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			).get_environ()
		)
		previous_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = manager
		try:
			with self.set_request(request):
				return EmailPasswordProvider().authenticate({"email": email, "password": password}).token
		finally:
			frappe.local.login_manager = previous_manager

	def _new_email(self) -> str:
		import uuid

		return f"ceto.reg.{uuid.uuid4().hex[:12]}@example.com"
