import frappe

from ceto.api.auth.verification import confirm_customer_verification, request_customer_verification
from ceto.services.auth.verification import is_verified
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER
from ceto.tests.utils import CetoTestSuite

_requested_verifications: list[dict] = []
_confirmed_verifications: list[dict] = []


def capture_requested_verification(**payload):
	_requested_verifications.append(payload)


def capture_confirmed_verification(**payload):
	_confirmed_verifications.append(payload)


class TestVerification(CetoTestSuite):
	def setUp(self):
		_requested_verifications.clear()
		_confirmed_verifications.clear()

	def test_request_and_confirm_verification(self):
		hooks = {
			"ceto_auth_verification_requested": [
				"ceto.tests.api.auth.test_verification.capture_requested_verification"
			],
			"ceto_auth_verification_confirmed": [
				"ceto.tests.api.auth.test_verification.capture_confirmed_verification"
			],
		}
		with self.patch_hooks(hooks):
			response = request_customer_verification(
				entity_id=TEST_CUSTOMER.upper(),
				entity_type="email",
				code_provider="token",
				metadata={"source": "test"},
			)
			self.assertEqual(response.status_code, 201)
			self.assertEqual(response.get_data(), b"")
			self.assertEqual(len(_requested_verifications), 1)

			request_event = _requested_verifications[0]
			self.assertEqual(request_event["entity_id"], TEST_CUSTOMER)
			self.assertEqual(request_event["metadata"], {"source": "test"})
			self.assertNotIn(TEST_CUSTOMER, request_event["code"])

			response = confirm_customer_verification(code=request_event["code"])
			self.assertEqual(response.status_code, 200)
			self.assertEqual(response.get_data(), b"")
			self.assertTrue(is_verified("email", TEST_CUSTOMER))
			self.assertEqual(_confirmed_verifications[0]["entity_id"], TEST_CUSTOMER)

			with self.assertRaises(frappe.ValidationError):
				confirm_customer_verification(code=request_event["code"])

	def test_rejects_unsupported_code_provider(self):
		with self.assertRaises(frappe.ValidationError):
			request_customer_verification(
				entity_id=TEST_CUSTOMER,
				entity_type="email",
				code_provider="sms",
			)
