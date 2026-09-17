from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import ANY, MagicMock, patch

import jwt

from ceto.api.auth.authentication import authenticate, authenticate_callback
from ceto.api.auth.providers import list_customer_auth_providers
from ceto.routing import JSON
from ceto.services.auth.authentication import authenticate_customer
from ceto.services.auth.oauth import complete_google_auth, start_google_auth
from ceto.services.auth.tokens import create_customer_token, decode_customer_token
from ceto.types.http.auth import AuthProvidersListResponse, AuthResponse

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"


class TestCustomerAuth(TestCase):
	@patch("ceto.services.auth.providers.is_google_auth_enabled", return_value=False)
	def test_list_providers(self, _google_enabled):
		result = list_customer_auth_providers()

		self.assertIsInstance(result, JSON)
		self.assertIsInstance(result.value, AuthProvidersListResponse)
		self.assertEqual(
			result.value.model_dump(mode="json"),
			{
				"providers": [
					{
						"id": "emailpass",
						"identifier": "emailpass",
						"display_name": "Email and password",
						"flow": "credentials",
					}
				]
			},
		)

	@patch("ceto.services.auth.providers.is_google_auth_enabled", return_value=True)
	def test_list_providers_includes_configured_google(self, _google_enabled):
		result = list_customer_auth_providers()

		self.assertEqual(
			result.value.providers[1].model_dump(mode="json"),
			{
				"id": "google",
				"identifier": "google",
				"display_name": "Google",
				"flow": "redirect",
			},
		)

	@patch("ceto.api.auth.authentication.authenticate_customer", return_value="customer-jwt")
	def test_authenticate_endpoint(self, authenticate_service):
		response = authenticate(
			"emailpass",
			email="customer@example.com",
			password="correct horse battery staple",
		)

		self.assertIsInstance(response, JSON)
		self.assertIsInstance(response.value, AuthResponse)
		self.assertEqual(response.value.token, "customer-jwt")
		authenticate_service.assert_called_once_with(
			auth_provider="emailpass",
			email="customer@example.com",
			password="correct horse battery staple",
		)

	@patch("ceto.api.auth.authentication.start_google_auth", return_value="https://accounts.google.test/auth")
	def test_starts_google_auth(self, start_google_auth):
		response = authenticate("google", callback_url="https://shop.example.com/auth/google")

		self.assertEqual(response.value.location, "https://accounts.google.test/auth")
		start_google_auth.assert_called_once_with("https://shop.example.com/auth/google")

	@patch("ceto.api.auth.authentication.complete_google_auth", return_value="customer-jwt")
	def test_completes_google_auth(self, complete_google_auth):
		response = authenticate_callback("google", code="google-code", state="oauth-state")

		self.assertEqual(response.value.token, "customer-jwt")
		complete_google_auth.assert_called_once_with(code="google-code", state="oauth-state")

	@patch("ceto.services.auth.authentication.create_customer_token", return_value="customer-jwt")
	@patch("ceto.services.auth.authentication.should_run_2fa", return_value=False)
	@patch("ceto.services.auth.authentication.validate_ip_address")
	@patch("ceto.services.auth.authentication.frappe")
	def test_authenticate_email_password(self, mock_frappe, _validate_ip, _two_factor, _token):
		login_manager = mock_frappe.local.login_manager
		login_manager.user = "customer@example.com"
		login_manager.force_user_to_reset_password.return_value = False
		mock_frappe.get_system_settings.return_value = False
		mock_frappe.db.get_value.return_value = "Website User"

		token = authenticate_customer(
			"emailpass",
			email="customer@example.com",
			password="correct horse battery staple",
		)

		self.assertEqual(token, "customer-jwt")
		login_manager.authenticate.assert_called_once_with(
			user="customer@example.com",
			pwd="correct horse battery staple",
		)

	@patch("ceto.services.auth.tokens._token_expiry_seconds", return_value=3600)
	@patch("ceto.services.auth.tokens._jwt_secret", return_value=TEST_SECRET)
	def test_customer_token_round_trip(self, _secret, _expiry):
		token = create_customer_token("customer@example.com")
		claims = decode_customer_token(token)

		self.assertEqual(claims["sub"], "customer@example.com")
		self.assertEqual(claims["actor_type"], "customer")
		self.assertEqual(claims["iss"], "ceto")
		self.assertGreater(claims["exp"], claims["iat"])

	@patch("ceto.services.auth.tokens._token_expiry_seconds", return_value=3600)
	@patch("ceto.services.auth.tokens._jwt_secret", return_value=TEST_SECRET)
	def test_customer_token_rejects_wrong_secret(self, _secret, _expiry):
		token = create_customer_token("customer@example.com")
		with patch(
			"ceto.services.auth.tokens._jwt_secret",
			return_value="a-different-test-secret-that-is-over-32-bytes",
		):
			with self.assertRaises(jwt.InvalidTokenError):
				decode_customer_token(token)


class TestGoogleOAuthService(TestCase):
	@patch("ceto.services.auth.oauth.is_google_auth_enabled", return_value=True)
	@patch("ceto.services.auth.oauth.get_oauth2_providers")
	@patch("ceto.services.auth.oauth.get_oauth2_flow")
	@patch("ceto.services.auth.oauth.frappe")
	def test_start_google_auth_stores_state_and_builds_redirect(
		self, mock_frappe, get_flow, get_providers, _enabled
	):
		mock_frappe.generate_hash.return_value = "oauth-state"
		get_providers.return_value = {
			"google": {"auth_url_data": {"scope": "openid email", "response_type": "code"}}
		}
		get_flow.return_value.get_authorize_url.return_value = "https://accounts.google.test/auth"

		location = start_google_auth("https://shop.example.com/auth/google")

		self.assertEqual(location, "https://accounts.google.test/auth")
		mock_frappe.cache.set_value.assert_called_once_with(
			"ceto:oauth:google:oauth-state",
			{"callback_url": "https://shop.example.com/auth/google"},
			expires_in_sec=600,
		)
		get_flow.return_value.get_authorize_url.assert_called_once_with(
			redirect_uri="https://shop.example.com/auth/google",
			state="oauth-state",
			scope="openid email",
			response_type="code",
		)

	@patch("ceto.services.auth.oauth.create_customer_token", return_value="customer-jwt")
	@patch("ceto.services.auth.oauth.update_oauth_user")
	@patch("ceto.services.auth.oauth.get_oauth2_providers")
	@patch("ceto.services.auth.oauth.get_oauth2_flow")
	@patch("ceto.services.auth.oauth.is_google_auth_enabled", return_value=True)
	@patch("ceto.services.auth.oauth.frappe")
	def test_complete_google_auth_provisions_website_user(
		self,
		mock_frappe,
		_enabled,
		get_flow,
		get_providers,
		update_user,
		create_token,
	):
		mock_frappe.cache.get_value.return_value = {"callback_url": "https://shop.example.com/auth/google"}
		mock_frappe.db.get_value.side_effect = [None, SimpleNamespace(enabled=1, user_type="Website User")]
		get_providers.return_value = {"google": {"api_endpoint": "oauth2/v2/userinfo"}}
		session = MagicMock()
		session.get.return_value.json.return_value = {
			"id": "google-user-id",
			"email": "Customer@Example.com",
			"email_verified": True,
		}
		get_flow.return_value.get_auth_session.return_value = session

		token = complete_google_auth("google-code", "oauth-state")

		self.assertEqual(token, "customer-jwt")
		mock_frappe.cache.delete_value.assert_called_once_with("ceto:oauth:google:oauth-state")
		get_flow.return_value.get_auth_session.assert_called_once_with(
			data={
				"code": "google-code",
				"redirect_uri": "https://shop.example.com/auth/google",
				"grant_type": "authorization_code",
			},
			decoder=ANY,
		)
		update_user.assert_called_once_with(
			"customer@example.com",
			{
				"id": "google-user-id",
				"email": "Customer@Example.com",
				"email_verified": True,
			},
			"google",
		)
		create_token.assert_called_once_with("customer@example.com")
