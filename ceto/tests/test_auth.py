from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import frappe
import jwt
from frappe.auth import LoginManager
from rauth import OAuth2Service
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.api.auth.authentication import authenticate, authenticate_callback
from ceto.api.auth.providers import list_customer_auth_providers
from ceto.routing import JSON
from ceto.services.auth.providers.google import GoogleProvider
from ceto.services.auth.tokens import authenticate_bearer_token, create_customer_token, decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import (
	TEST_CUSTOMER,
	TEST_CUSTOMER_PASSWORD,
	TEST_DISABLED_CUSTOMER,
	TEST_SYSTEM_USER,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.auth import AuthProvidersListResponse, AuthResponse, EmailPasswordInput

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"
OTHER_TEST_SECRET = "a-different-test-secret-that-is-over-32-bytes"


class OAuthSession:
	def __init__(self, user_info: dict) -> None:
		self.user_info = user_info

	def get(self, _url: str, **_kwargs):
		return self

	def json(self) -> dict:
		return self.user_info


class TestCustomerAuth(CetoTestSuite):
	def test_list_providers_uses_social_login_configuration(self):
		result = list_customer_auth_providers()
		self.assertIsInstance(result, AuthProvidersListResponse)
		self.assertEqual([provider.identifier for provider in result.providers], ["emailpass"])

		with self.change_settings("Social Login Key", {"enable_social_login": 1}, docname="google"):
			result = list_customer_auth_providers()

		self.assertEqual([provider.identifier for provider in result.providers], ["emailpass", "google"])
		self.assertEqual(result.providers[1].flow, "redirect")

	def test_authenticate_endpoint_uses_real_website_user(self):
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

	def test_email_is_normalized_without_stripping_password(self):
		data = EmailPasswordInput.model_validate({"email": f" {TEST_CUSTOMER} ", "password": " secret "})
		self.assertEqual(str(data.email), TEST_CUSTOMER)
		self.assertEqual(data.password.get_secret_value(), " secret ")

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
	def _login_manager() -> LoginManager:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		return manager

	@staticmethod
	def _bearer_headers(user: str) -> dict[str, str]:
		return {"Authorization": f"Bearer {create_customer_token(user)}"}

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())


class TestGoogleOAuthService(CetoTestSuite):
	def test_start_google_auth_uses_configured_provider_and_stores_state(self):
		with self.change_settings("Social Login Key", {"enable_social_login": 1}, docname="google"):
			location = GoogleProvider()._start_auth("https://shop.example.com/auth/google")

		query = parse_qs(urlparse(location).query)
		self.assertEqual(query["client_id"], ["ceto-test-google-client"])
		self.assertEqual(query["redirect_uri"], ["https://shop.example.com/auth/google"])
		state = query["state"][0]
		self.assertEqual(
			frappe.cache.get_value(f"ceto:oauth:google:{state}"),
			{"callback_url": "https://shop.example.com/auth/google"},
		)

	def test_complete_google_auth_consumes_state_and_returns_customer_token(self):
		provider = GoogleProvider()
		with self.change_settings("Social Login Key", {"enable_social_login": 1}, docname="google"):
			location = provider._start_auth("https://shop.example.com/auth/google")
			state = parse_qs(urlparse(location).query)["state"][0]
			session = OAuthSession(
				{
					"id": "ceto-google-user-id",
					"email": TEST_CUSTOMER,
					"email_verified": True,
					"given_name": "Ceto",
				}
			)
			# The OAuth token exchange is the sole external boundary in this test.
			with patch.object(OAuth2Service, "get_auth_session", return_value=session):
				response = authenticate_callback("google", code="google-code", state=state)

		self.assertEqual(decode_customer_token(response.value.token)["sub"], TEST_CUSTOMER)
		with self.assertRaises(frappe.AuthenticationError):
			provider._consume_callback_url(state)
