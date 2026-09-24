from datetime import UTC, datetime, timedelta

import frappe
import jwt
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.services.auth.tokens import authenticate_bearer_token, create_customer_token, decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import (
	TEST_CUSTOMER,
	TEST_DISABLED_CUSTOMER,
	TEST_SYSTEM_USER,
)
from ceto.tests.utils import CetoTestSuite

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"
OTHER_TEST_SECRET = "a-different-test-secret-that-is-over-32-bytes"


class TestTokens(CetoTestSuite):
	def test_customer_token_round_trip_and_wrong_secret(self):
		with self.set_conf(ceto_jwt_secret=TEST_SECRET, ceto_jwt_expiry_seconds=3600):
			token = create_customer_token(TEST_CUSTOMER)
			claims = decode_customer_token(token)

		self.assertEqual(claims["sub"], TEST_CUSTOMER)
		self.assertEqual(claims["actor_type"], "customer")
		self.assertEqual(claims["iss"], "ceto")
		self.assertGreater(claims["exp"], claims["iat"])

		with self.set_conf(ceto_jwt_secret=OTHER_TEST_SECRET):
			with self.assertRaises(jwt.InvalidTokenError):
				decode_customer_token(token)

	def test_bearer_hook_authenticates_valid_customer(self):
		request = self._request("/ceto/account", "GET", headers=self._bearer_headers(TEST_CUSTOMER))
		with self.set_user("Guest"), self.set_request(request):
			authenticate_bearer_token()
			self.assertEqual(frappe.session.user, TEST_CUSTOMER)

	def test_bearer_hook_rejects_wrong_secret(self):
		with self.set_conf(ceto_jwt_secret=TEST_SECRET):
			token = create_customer_token(TEST_CUSTOMER)
		request = self._request("/ceto/account", "GET", headers={"Authorization": f"Bearer {token}"})
		with (
			self.set_conf(ceto_jwt_secret=OTHER_TEST_SECRET),
			self.set_user("Guest"),
			self.set_request(request),
			self.assertRaises(frappe.AuthenticationError),
		):
			authenticate_bearer_token()

	def test_bearer_hook_rejects_disabled_or_system_user(self):
		for user in (TEST_DISABLED_CUSTOMER, TEST_SYSTEM_USER):
			with self.subTest(user=user):
				request = self._request("/ceto/account", "GET", headers=self._bearer_headers(user))
				with (
					self.set_user("Guest"),
					self.set_request(request),
					self.assertRaises(frappe.AuthenticationError),
				):
					authenticate_bearer_token()

	def test_bearer_hook_ignores_non_jwt_bearer(self):
		request = self._request("/ceto/account", "GET", headers={"Authorization": "Bearer opaque-token"})
		with self.set_user("Guest"), self.set_request(request):
			authenticate_bearer_token()
			self.assertEqual(frappe.session.user, "Guest")

	def test_bearer_hook_rejects_non_customer_actor(self):
		now = datetime.now(UTC)
		with self.set_conf(ceto_jwt_secret=TEST_SECRET):
			token = jwt.encode(
				{
					"sub": TEST_SYSTEM_USER,
					"actor_type": "admin",
					"iss": "ceto",
					"iat": now,
					"exp": now + timedelta(hours=1),
				},
				TEST_SECRET,
				algorithm="HS256",
			)
		request = self._request("/ceto/account", "GET", headers={"Authorization": f"Bearer {token}"})
		with (
			self.set_user("Guest"),
			self.set_request(request),
			self.assertRaises(frappe.AuthenticationError),
		):
			authenticate_bearer_token()

	@staticmethod
	def _bearer_headers(user: str) -> dict[str, str]:
		return {"Authorization": f"Bearer {create_customer_token(user)}"}

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())

	def test_decode_rejects_unexpected_purpose(self):
		from ceto.services.auth.tokens import (
			create_customer_password_reset_token,
			create_customer_registration_token,
		)

		for token in (
			create_customer_password_reset_token(TEST_CUSTOMER),
			create_customer_registration_token(TEST_CUSTOMER),
		):
			with self.subTest(token=token[:16]):
				with self.assertRaises(jwt.InvalidTokenError):
					decode_customer_token(token)

	def test_bearer_hook_ignores_single_purpose_tokens(self):
		from ceto.services.auth.tokens import (
			create_customer_password_reset_token,
			create_customer_registration_token,
		)

		for token in (
			create_customer_password_reset_token(TEST_CUSTOMER),
			create_customer_registration_token(TEST_CUSTOMER),
		):
			with self.subTest(token=token[:16]):
				request = self._request("/ceto/account", "GET", headers={"Authorization": f"Bearer {token}"})
				with self.set_user("Guest"), self.set_request(request):
					authenticate_bearer_token()
					self.assertEqual(frappe.session.user, "Guest")

	def test_get_bearer_password_reset_user_resolves_customer(self):
		from ceto.services.auth.tokens import (
			create_customer_password_reset_token,
			get_bearer_password_reset_user,
		)

		token = create_customer_password_reset_token(TEST_CUSTOMER)
		request = self._request(
			"/ceto/auth/customer/emailpass/update",
			"POST",
			headers={"Authorization": f"Bearer {token}"},
		)
		with self.set_request(request):
			self.assertEqual(get_bearer_password_reset_user(), TEST_CUSTOMER)

	def test_single_purpose_token_expiry_settings(self):
		from ceto.services.auth.tokens import (
			create_customer_password_reset_token,
			create_customer_registration_token,
		)

		with self.set_conf(ceto_password_reset_token_expiry_seconds=120):
			token = create_customer_password_reset_token(TEST_CUSTOMER)
			claims = decode_customer_token(token, purpose="password_reset")
			self.assertEqual(claims["exp"] - claims["iat"], 120)

		with self.set_conf(ceto_registration_token_expiry_seconds=300):
			token = create_customer_registration_token(TEST_CUSTOMER)
			claims = decode_customer_token(token, purpose="registration")
			self.assertEqual(claims["exp"] - claims["iat"], 300)
