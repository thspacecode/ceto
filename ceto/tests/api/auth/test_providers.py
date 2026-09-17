import frappe

from ceto.api.auth.providers import list_customer_auth_providers
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.auth import AuthProvidersListResponse


class TestProviders(CetoTestSuite):
	def test_endpoint_is_not_whitelisted(self):
		self.assertNotIn(list_customer_auth_providers, frappe.whitelisted)
		self.assertFalse(hasattr(list_customer_auth_providers, "is_whitelisted"))

	def test_list_uses_social_login_configuration(self):
		result = list_customer_auth_providers()
		self.assertIsInstance(result, AuthProvidersListResponse)
		self.assertEqual([provider.identifier for provider in result.providers], ["emailpass"])

		with self.change_settings("Social Login Key", {"enable_social_login": 1}, docname="google"):
			result = list_customer_auth_providers()

		self.assertEqual([provider.identifier for provider in result.providers], ["emailpass", "google"])
		self.assertEqual(result.providers[1].flow, "redirect")
