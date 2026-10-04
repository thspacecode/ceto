from datetime import UTC, datetime, timedelta

import frappe
import jwt
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.services.auth.tokens import (
	consume_bearer_registration_token,
	create_customer_password_reset_token,
	create_customer_registration_token,
	create_customer_token,
	decode_customer_token,
	get_bearer_password_reset_user,
	get_bearer_registration_user,
)
from ceto.tests.data.bootstrap_test_master_data import (
	TEST_CUSTOMER,
	TEST_DISABLED_CUSTOMER,
	TEST_SYSTEM_USER,
)
from ceto.tests.utils import CetoTestSuite

TEST_SECRET = "a-test-only-signing-secret-that-is-at-least-32-bytes"
REGISTRATION_PATH = "/ceto/store/customers"


class TestRegistrationTokens(CetoTestSuite):
	def test_check_resolves_registration_subject(self):
		token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")
		request = self._bearer_request(token)

		with self.set_request(request):
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)

	def test_check_does_not_consume_token(self):
		token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")

		with self.set_request(self._bearer_request(token)):
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)

	def test_check_requires_bearer_token(self):
		with (
			self.set_request(self._bearer_request(None)),
			self.assertRaises(frappe.AuthenticationError),
		):
			get_bearer_registration_user("emailpass")

	def test_check_rejects_other_provider(self):
		token = create_customer_registration_token(TEST_CUSTOMER, "google")

		with (
			self.set_request(self._bearer_request(token)),
			self.assertRaises(frappe.AuthenticationError),
		):
			get_bearer_registration_user("emailpass")

	def test_check_rejects_other_purposes(self):
		for token in (
			create_customer_token(TEST_CUSTOMER),
			create_customer_password_reset_token(TEST_CUSTOMER, "emailpass"),
		):
			with self.subTest(token=token[:16]):
				with (
					self.set_request(self._bearer_request(token)),
					self.assertRaises(frappe.AuthenticationError),
				):
					get_bearer_registration_user("emailpass")

	def test_check_rejects_expired_token(self):
		issued_at = datetime.now(UTC) - timedelta(hours=2)
		with self.set_conf(ceto_jwt_secret=TEST_SECRET):
			token = jwt.encode(
				{
					"sub": TEST_CUSTOMER,
					"actor_type": "customer",
					"purpose": "registration",
					"provider": "emailpass",
					"iss": "ceto",
					"iat": issued_at,
					"exp": issued_at + timedelta(hours=1),
					"jti": "expired-registration-jti",
				},
				TEST_SECRET,
				algorithm="HS256",
			)

			with (
				self.set_request(self._bearer_request(token)),
				self.assertRaises(frappe.AuthenticationError),
			):
				get_bearer_registration_user("emailpass")

	def test_check_rejects_unusable_subject(self):
		for user in (TEST_DISABLED_CUSTOMER, TEST_SYSTEM_USER, "nobody@example.com"):
			with self.subTest(user=user):
				token = create_customer_registration_token(user, "emailpass")
				with (
					self.set_request(self._bearer_request(token)),
					self.assertRaises(frappe.AuthenticationError),
				):
					get_bearer_registration_user("emailpass")

	def test_consume_makes_token_single_use(self):
		token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")

		with self.set_request(self._bearer_request(token)):
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)
			consume_bearer_registration_token()
			with self.assertRaises(frappe.AuthenticationError):
				get_bearer_registration_user("emailpass")

	def test_consume_ignores_invalid_bearer(self):
		with self.set_request(self._bearer_request(None)):
			consume_bearer_registration_token()
		with self.set_request(self._bearer_request("opaque-token")):
			consume_bearer_registration_token()
		with self.set_request(self._bearer_request(create_customer_token(TEST_CUSTOMER))):
			consume_bearer_registration_token()

		# Nothing above may poison the next registration token.
		token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")
		with self.set_request(self._bearer_request(token)):
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)

	def test_consume_survives_database_rollback(self):
		token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")

		with self.set_request(self._bearer_request(token)):
			self.assertEqual(get_bearer_registration_user("emailpass"), TEST_CUSTOMER)
			consume_bearer_registration_token()
			# The used-marker lives in cache, outside the database transaction:
			# no rollback can release it, so callers must consume only after
			# their profile transaction succeeded.
			frappe.db.rollback()
			with self.assertRaises(frappe.AuthenticationError):
				get_bearer_registration_user("emailpass")

	def test_consume_state_is_bounded_by_token_expiry(self):
		with self.set_conf(ceto_registration_token_expiry_seconds=120):
			token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")
			jti = decode_customer_token(token, purpose="registration")["jti"]

			with self.set_request(self._bearer_request(token)):
				consume_bearer_registration_token()

			ttl = frappe.cache().ttl(frappe.cache().make_key(f"ceto_registration_used::{jti}"))
			self.assertGreater(ttl, 0)
			self.assertLessEqual(ttl, 120)

	def test_reset_flow_is_unaffected_by_registration_markers(self):
		registration_token = create_customer_registration_token(TEST_CUSTOMER, "emailpass")
		reset_token = create_customer_password_reset_token(TEST_CUSTOMER, "emailpass")

		with self.set_request(self._bearer_request(registration_token)):
			consume_bearer_registration_token()
		with self.set_request(self._bearer_request(reset_token)):
			self.assertEqual(get_bearer_password_reset_user("emailpass"), TEST_CUSTOMER)

	@staticmethod
	def _bearer_request(token: str | None) -> Request:
		headers = {"Authorization": f"Bearer {token}"} if token else {}
		return Request(
			EnvironBuilder(
				REGISTRATION_PATH,
				"POST",
				headers=headers,
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			).get_environ()
		)
