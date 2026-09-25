import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.api.auth.credentials import (
	generate_customer_password_reset_token,
	register_customer,
	update_customer_authentication,
)
from ceto.routing import JSON
from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.auth import AuthResponse

_delivered_reset_tokens: list[dict] = []


def capture_reset_token(**payload):
	_delivered_reset_tokens.append(payload)


class TestCredentials(CetoTestSuite):
	def setUp(self):
		_delivered_reset_tokens.clear()

	def test_endpoints_are_not_whitelisted(self):
		for endpoint in (
			register_customer,
			update_customer_authentication,
			generate_customer_password_reset_token,
		):
			self.assertNotIn(endpoint, frappe.whitelisted)
			self.assertFalse(hasattr(endpoint, "is_whitelisted"))

	def test_register_returns_registration_token(self):
		email = self._new_email()
		response = register_customer("emailpass", email=email, password=TEST_CUSTOMER_PASSWORD)

		self.assertIsInstance(response, JSON)
		self.assertIsInstance(response.value, AuthResponse)
		claims = decode_customer_token(response.value.token, purpose="registration")
		self.assertEqual(claims["sub"], email.lower())
		self.assertFalse(frappe.db.exists("User", email))

	def test_register_rejects_existing_customer(self):
		with self.assertRaises(frappe.DuplicateEntryError):
			register_customer("emailpass", email=TEST_CUSTOMER, password=TEST_CUSTOMER_PASSWORD)

	def test_reset_password_delivers_token_to_hooks(self):
		hooks = {"ceto_auth_password_reset": ["ceto.tests.api.auth.test_credentials.capture_reset_token"]}
		with self.patch_hooks(hooks):
			response = generate_customer_password_reset_token("emailpass", identifier=TEST_CUSTOMER)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(len(_delivered_reset_tokens), 1)
		event = _delivered_reset_tokens[0]
		self.assertEqual(event["identifier"], TEST_CUSTOMER)
		self.assertEqual(
			decode_customer_token(event["token"], purpose="password_reset")["sub"], TEST_CUSTOMER
		)

	def test_reset_password_is_identical_for_unknown_identifier(self):
		hooks = {"ceto_auth_password_reset": ["ceto.tests.api.auth.test_credentials.capture_reset_token"]}
		with self.patch_hooks(hooks):
			response = generate_customer_password_reset_token("emailpass", identifier="nobody@example.com")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(_delivered_reset_tokens, [])

	def test_update_credentials_consumes_reset_token(self):
		token = self._reset_token_for(TEST_CUSTOMER)
		new_password = "A brand new correct horse battery staple 7!"
		request = self._request(
			"/ceto/auth/customer/emailpass/update",
			"POST",
			headers={"Authorization": f"Bearer {token}"},
		)

		with self.set_request(request):
			response = update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=new_password)

		self.assertEqual(response.success, True)
		from frappe.utils.password import check_password

		check_password(TEST_CUSTOMER, new_password)
		with self.assertRaises(frappe.AuthenticationError):
			check_password(TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD)

	def test_update_credentials_rejects_mismatched_email(self):
		other = self._new_email()
		self._insert_website_user(other)
		token = self._reset_token_for(other)
		request = self._request(
			"/ceto/auth/customer/emailpass/update",
			"POST",
			headers={"Authorization": f"Bearer {token}"},
		)

		with (
			self.set_request(request),
			self.assertRaises(frappe.ValidationError),
		):
			update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=TEST_CUSTOMER_PASSWORD)

	def test_update_credentials_rejects_replayed_reset_token(self):
		token = self._reset_token_for(TEST_CUSTOMER)
		new_password = "A brand new correct horse battery staple 7!"
		request = self._request(
			"/ceto/auth/customer/emailpass/update",
			"POST",
			headers={"Authorization": f"Bearer {token}"},
		)

		with self.set_request(request):
			update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=new_password)
			with self.assertRaises(frappe.AuthenticationError):
				update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=new_password)

	def test_update_credentials_rejects_token_from_other_provider(self):
		from ceto.services.auth.tokens import create_customer_password_reset_token

		token = create_customer_password_reset_token(TEST_CUSTOMER, "some-other-provider")
		request = self._request(
			"/ceto/auth/customer/emailpass/update",
			"POST",
			headers={"Authorization": f"Bearer {token}"},
		)

		with (
			self.set_request(request),
			self.assertRaises(frappe.AuthenticationError),
		):
			update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=TEST_CUSTOMER_PASSWORD)

	def test_update_credentials_requires_reset_token(self):
		request = self._request("/ceto/auth/customer/emailpass/update", "POST")
		with (
			self.set_request(request),
			self.assertRaises(frappe.AuthenticationError),
		):
			update_customer_authentication("emailpass", email=TEST_CUSTOMER, password=TEST_CUSTOMER_PASSWORD)

	def _reset_token_for(self, user: str) -> str:
		from ceto.services.auth.tokens import create_customer_password_reset_token

		return create_customer_password_reset_token(user, "emailpass")

	def _new_email(self) -> str:
		import uuid

		return f"ceto.cred.{uuid.uuid4().hex[:12]}@example.com"

	def _insert_website_user(self, email: str) -> None:
		user = frappe.new_doc("User")
		user.email = email
		user.first_name = "Ceto Cred Test"
		user.user_type = "Website User"
		user.send_welcome_email = 0
		user.flags.ignore_permissions = True
		user.insert()

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())
