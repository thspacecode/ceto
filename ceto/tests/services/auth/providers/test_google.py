from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import frappe
from rauth import OAuth2Service

from ceto.api.auth.authentication import authenticate_callback
from ceto.services.auth.providers.google import GoogleProvider
from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER
from ceto.tests.utils import CetoTestSuite


class OAuthSession:
	def __init__(self, user_info: dict) -> None:
		self.user_info = user_info

	def get(self, _url: str, **_kwargs):
		return self

	def json(self) -> dict:
		return self.user_info


class TestGoogleProvider(CetoTestSuite):
	def test_start_auth_uses_configured_provider_and_stores_state(self):
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

	def test_complete_auth_consumes_state_and_returns_customer_token(self):
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
