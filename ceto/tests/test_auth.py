from unittest import TestCase
from unittest.mock import patch

import jwt

from ceto.api.auth.customer import authenticate, providers
from ceto.api.auth.schemas import AuthProvidersListResponse, AuthResponse
from ceto.routing import JSON
from ceto.services.auth.customer import authenticate_customer
from ceto.services.auth.tokens import create_customer_token, decode_customer_token

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"


class TestCustomerAuth(TestCase):
	def test_list_providers(self):
		result = providers()

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

	@patch("ceto.api.auth.customer.authenticate_customer", return_value="customer-jwt")
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

	@patch("ceto.services.auth.customer.create_customer_token", return_value="customer-jwt")
	@patch("ceto.services.auth.customer.should_run_2fa", return_value=False)
	@patch("ceto.services.auth.customer.validate_ip_address")
	@patch("ceto.services.auth.customer.frappe")
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
