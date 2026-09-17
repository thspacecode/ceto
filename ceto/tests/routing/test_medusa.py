from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from ceto.routing.medusa import CetoPageRenderer, normalize_ceto_error
from ceto.tests.utils import CetoTestSuite


class TestMedusa(CetoTestSuite):
	def test_page_renderer_claims_only_ceto_namespace(self):
		self.assertTrue(CetoPageRenderer("ceto/auth/customer/providers").can_render())
		self.assertTrue(CetoPageRenderer("ceto").can_render())
		self.assertFalse(CetoPageRenderer("store").can_render())
		self.assertFalse(CetoPageRenderer("cetostore").can_render())

	def test_normalizes_errors_raised_before_dispatch(self):
		for status, expected in (
			(401, {"type": "unauthorized", "message": "Authentication required"}),
			(417, {"type": "not_allowed", "message": "Not permitted"}),
		):
			with self.subTest(status=status):
				response = Response("error", status=status, content_type="text/html")
				request = self._request("/ceto/store/orders", "POST")
				with self.set_flags(ceto_api_response=False):
					normalize_ceto_error(response, request)
				self.assertEqual(response.content_type, "application/json")
				self.assertEqual(response.get_json(), expected)

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())
