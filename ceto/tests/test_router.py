from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

import frappe
from ceto.api.auth.customer import authenticate, providers
from ceto.routing import router
from ceto.routing.medusa import normalize_response


class TestRouter(TestCase):
	def test_decorator_uses_frappe_whitelist(self):
		self.assertIn(providers, frappe.whitelisted)
		self.assertIn(authenticate, frappe.whitelisted)
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[providers], ["GET"])
		self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[authenticate], ["POST"])

	def test_matches_static_route(self):
		request = Request(EnvironBuilder(path="/auth/customer/providers", method="GET").get_environ())

		endpoint, arguments = router.match(request)

		self.assertEqual(endpoint, "ceto.api.auth.customer.providers")
		self.assertEqual(arguments, {})

	def test_matches_fastapi_style_path_parameter(self):
		request = Request(EnvironBuilder(path="/auth/customer/emailpass", method="POST").get_environ())

		endpoint, arguments = router.match(request)

		self.assertEqual(endpoint, "ceto.api.auth.customer.authenticate")
		self.assertEqual(arguments, {"auth_provider": "emailpass"})

	@patch("ceto.routing.medusa.frappe")
	def test_normalizes_frappe_rpc_response(self, mock_frappe):
		mock_frappe.flags = SimpleNamespace(ceto_medusa_request=True)
		response = Response(
			'{"message":{"token":"customer-jwt"}}',
			status=200,
			content_type="application/json",
		)

		normalize_response(response, Request({}))

		self.assertEqual(response.get_json(), {"token": "customer-jwt"})
