from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request, Response

from ceto.api.auth.authentication import authenticate, authenticate_callback
from ceto.api.auth.providers import list_customer_auth_providers
from ceto.routing import Router, ceto_router
from ceto.routing.medusa import CetoPageRenderer, normalize_ceto_error


class TestRouter(TestCase):
	def test_decorator_does_not_use_frappe_whitelist(self):
		self.assertNotIn(list_customer_auth_providers, frappe.whitelisted)
		self.assertNotIn(authenticate, frappe.whitelisted)
		self.assertNotIn(authenticate_callback, frappe.whitelisted)
		self.assertFalse(hasattr(list_customer_auth_providers, "is_whitelisted"))
		self.assertFalse(hasattr(authenticate, "is_whitelisted"))

	def test_ceto_router_applies_prefix_and_matches_static_route(self):
		request = self._request("/ceto/auth/customer/providers", "GET")

		route, arguments = ceto_router.match(request)

		self.assertEqual(route.path, "/ceto/auth/customer/providers")
		self.assertEqual(route.dotted_path, "ceto.api.auth.providers.list_customer_auth_providers")
		self.assertEqual(arguments, {})

	def test_matches_fastapi_style_path_parameter(self):
		request = self._request("/ceto/auth/customer/emailpass", "POST")

		route, arguments = ceto_router.match(request)

		self.assertEqual(route.path, "/ceto/auth/customer/{auth_provider}")
		self.assertEqual(route.dotted_path, "ceto.api.auth.authentication.authenticate")
		self.assertEqual(arguments, {"auth_provider": "emailpass"})

	def test_matches_authentication_callback_route(self):
		request = self._request("/ceto/auth/customer/google/callback", "GET")

		route, arguments = ceto_router.match(request)

		self.assertEqual(route.path, "/ceto/auth/customer/{auth_provider}/callback")
		self.assertEqual(route.dotted_path, "ceto.api.auth.authentication.authenticate_callback")
		self.assertEqual(arguments, {"auth_provider": "google"})

	@patch("ceto.routing.router.frappe.get_hooks", return_value={})
	@patch("ceto.services.auth.providers.google.GoogleProvider.is_enabled", return_value=True)
	@patch("ceto.services.auth.providers.google.GoogleProvider._complete_auth", return_value="customer-jwt")
	def test_dispatches_authentication_callback_query(self, complete_auth, _enabled, _hooks):
		response = ceto_router.dispatch(
			self._request(
				"/ceto/auth/customer/google/callback",
				"GET",
				query_string={"code": "google-code", "state": "oauth-state"},
			)
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"token": "customer-jwt"})
		complete_auth.assert_called_once_with(code="google-code", state="oauth-state")

	@patch("ceto.routing.router.frappe.get_hooks", return_value={})
	@patch("ceto.api.auth.providers.get_customer_auth_providers", return_value=[])
	def test_dispatches_endpoint_and_returns_direct_json(self, _providers, _hooks):
		response = ceto_router.dispatch(self._request("/ceto/auth/customer/providers", "GET"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"providers": []})
		self.assertNotIn("message", response.get_json())

	@patch("ceto.routing.router.frappe.get_hooks", return_value={})
	@patch(
		"ceto.services.auth.providers.emailpass.EmailPasswordProvider._authenticate_email_password",
		return_value="customer-jwt",
	)
	def test_dispatches_json_body_with_path_parameter(self, authenticate_email_password, _hooks):
		response = ceto_router.dispatch(
			self._request(
				"/ceto/auth/customer/emailpass",
				"POST",
				json={"email": "customer@example.com", "password": "secret"},
			)
		)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"token": "customer-jwt"})
		authenticate_email_password.assert_called_once_with(
			email="customer@example.com",
			password="secret",
		)

	def test_wrong_method_returns_medusa_405(self):
		response = ceto_router.dispatch(self._request("/ceto/auth/customer/emailpass", "GET"))

		self.assertEqual(response.status_code, 405)
		self.assertEqual(
			response.get_json(),
			{"type": "method_not_allowed", "message": "Method not allowed"},
		)
		self.assertEqual(response.headers["Allow"], "POST")

	def test_unknown_store_route_returns_medusa_404(self):
		response = ceto_router.dispatch(self._request("/ceto/unknown", "GET"))

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json(), {"type": "not_found", "message": "Route not found"})

	@patch("ceto.routing.router.frappe.get_hooks", return_value={})
	@patch("ceto.routing.router.frappe.log_error")
	def test_error_response_rolls_back_partial_writes(self, _log_error, _hooks):
		router = Router(prefix="/store")
		database = MagicMock()

		@router.post("/orders", allow_guest=True)
		def create_order():
			raise RuntimeError("failed after write")

		with patch("ceto.routing.router.frappe.local", SimpleNamespace(db=database)):
			response = router.dispatch(self._request("/store/orders", "POST"))

		self.assertEqual(response.status_code, 500)
		database.rollback.assert_called_once_with()

	def test_protected_route_rejects_guest(self):
		router = Router(prefix="/store")

		@router.get("/account")
		def account():
			return {"id": "customer"}

		with patch("ceto.routing.router.frappe.session", SimpleNamespace(user="Guest")):
			response = router.dispatch(self._request("/store/account", "GET"))

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json(), {"type": "unauthorized", "message": "Authentication required"})

	@patch("ceto.routing.router.frappe.get_hooks", return_value={})
	def test_protected_route_accepts_authenticated_user(self, _hooks):
		router = Router(prefix="/store")

		@router.get("/account")
		def account():
			return {"id": "customer"}

		with patch("ceto.routing.router.frappe.session", SimpleNamespace(user="customer@example.com")):
			response = router.dispatch(self._request("/store/account", "GET"))

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"id": "customer"})

	def test_duplicate_route_is_rejected(self):
		router = Router(prefix="/store")
		router.get("/products")(lambda: None)

		with self.assertRaisesRegex(ValueError, "Duplicate route: GET /store/products"):
			router.get("/products")(lambda: None)

	@patch("ceto.routing.router.frappe.get_attr")
	@patch("ceto.routing.router.frappe.get_hooks")
	def test_route_override_uses_external_route_key(self, get_hooks, get_attr):
		router = Router(prefix="/ceto")

		@router.get("/store/products", allow_guest=True)
		def products():
			return {"source": "ceto"}

		get_hooks.return_value = {"GET /ceto/store/products": ["shop.overrides.products"]}
		get_attr.return_value = lambda: {"source": "override"}

		response = router.dispatch(self._request("/ceto/store/products", "GET"))

		self.assertEqual(response.get_json(), {"source": "override"})
		get_attr.assert_called_once_with("shop.overrides.products")

	def test_page_renderer_claims_only_ceto_namespace(self):
		self.assertTrue(CetoPageRenderer("ceto/auth/customer/providers").can_render())
		self.assertTrue(CetoPageRenderer("ceto").can_render())
		self.assertFalse(CetoPageRenderer("store").can_render())
		self.assertFalse(CetoPageRenderer("cetostore").can_render())

	@patch("ceto.routing.medusa.frappe")
	def test_normalizes_auth_error_raised_before_dispatch(self, mock_frappe):
		mock_frappe.flags = SimpleNamespace(ceto_api_response=False)
		response = Response("login", status=401, content_type="text/html")
		request = self._request("/ceto/auth/customer/providers", "GET")

		normalize_ceto_error(response, request)

		self.assertEqual(response.content_type, "application/json")
		self.assertEqual(response.get_json(), {"type": "unauthorized", "message": "Authentication required"})

	@patch("ceto.routing.medusa.frappe")
	def test_normalizes_csrf_error_as_not_allowed(self, mock_frappe):
		mock_frappe.flags = SimpleNamespace(ceto_api_response=False)
		response = Response("csrf", status=417, content_type="text/html")
		request = self._request("/ceto/store/orders", "POST")

		normalize_ceto_error(response, request)

		self.assertEqual(response.status_code, 417)
		self.assertEqual(response.content_type, "application/json")
		self.assertEqual(response.get_json(), {"type": "not_allowed", "message": "Not permitted"})

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())
