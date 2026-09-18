from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.auth import EmailPasswordInput


class TestPayloads(CetoTestSuite):
	def test_email_is_normalized_without_stripping_password(self):
		data = EmailPasswordInput.model_validate({"email": f" {TEST_CUSTOMER} ", "password": " secret "})
		self.assertEqual(str(data.email), TEST_CUSTOMER)
		self.assertEqual(data.password.get_secret_value(), " secret ")
