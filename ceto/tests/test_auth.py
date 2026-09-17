from unittest import TestCase
from unittest.mock import patch

import jwt

from ceto.api.auth.customer import authenticate, providers
from ceto.api.auth.tokens import create_customer_token, decode_customer_token

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"


class TestCustomerAuth(TestCase):
	def test_list_providers(self):
		self.assertEqual(
			providers(),
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

	@patch("ceto.api.auth.customer.create_customer_token", return_value="customer-jwt")
	@patch("ceto.api.auth.customer.should_run_2fa", return_value=False)
	@patch("ceto.api.auth.customer.validate_ip_address")
	@patch("ceto.api.auth.customer.frappe")
	def test_authenticate_email_password(self, mock_frappe, _validate_ip, _two_factor, _token):
		login_manager = mock_frappe.local.login_manager
		login_manager.user = "customer@example.com"
		login_manager.force_user_to_reset_password.return_value = False
		mock_frappe.get_system_settings.return_value = False
		mock_frappe.db.get_value.return_value = "Website User"

		response = authenticate(
			"emailpass",
			email="customer@example.com",
			password="correct horse battery staple",
		)

		self.assertEqual(response, {"token": "customer-jwt"})
		login_manager.authenticate.assert_called_once_with(
			user="customer@example.com",
			pwd="correct horse battery staple",
		)

	@patch("ceto.api.auth.tokens._token_expiry_seconds", return_value=3600)
	@patch("ceto.api.auth.tokens._jwt_secret", return_value=TEST_SECRET)
	def test_customer_token_round_trip(self, _secret, _expiry):
		token = create_customer_token("customer@example.com")
		claims = decode_customer_token(token)

		self.assertEqual(claims["sub"], "customer@example.com")
		self.assertEqual(claims["actor_type"], "customer")
		self.assertEqual(claims["iss"], "ceto")
		self.assertGreater(claims["exp"], claims["iat"])

	@patch("ceto.api.auth.tokens._token_expiry_seconds", return_value=3600)
	@patch("ceto.api.auth.tokens._jwt_secret", return_value=TEST_SECRET)
	def test_customer_token_rejects_wrong_secret(self, _secret, _expiry):
		token = create_customer_token("customer@example.com")
		with patch(
			"ceto.api.auth.tokens._jwt_secret", return_value="a-different-test-secret-that-is-over-32-bytes"
		):
			with self.assertRaises(jwt.InvalidTokenError):
				decode_customer_token(token)
