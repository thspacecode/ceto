from uuid import uuid4

import frappe
from frappe.auth import LoginManager
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import Router, ceto_router
from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD
from ceto.tests.utils import CetoTestSuite


def overridden_products() -> dict[str, str]:
	return {"source": "override"}


class TestRouter(CetoTestSuite):
	def test_applies_prefix_and_matches_routes(self):
		for path, method, expected_path, arguments in (
			("/ceto/auth/customer/providers", "GET", "/ceto/auth/customer/providers", {}),
			(
				"/ceto/auth/customer/emailpass",
				"POST",
				"/ceto/auth/customer/{auth_provider}",
				{"auth_provider": "emailpass"},
			),
			(
				"/ceto/auth/customer/google/callback",
				"GET",
				"/ceto/auth/customer/{auth_provider}/callback",
				{"auth_provider": "google"},
			),
		):
			with self.subTest(path=path):
				route, matched_arguments = ceto_router.match(self._request(path, method))
				self.assertEqual(route.path, expected_path)
				self.assertEqual(matched_arguments, arguments)

	def test_dispatches_endpoint_and_returns_direct_json(self):
		response = ceto_router.dispatch(self._request("/ceto/auth/customer/providers", "GET"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			response.get_json(),
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
		self.assertNotIn("message", response.get_json())

	def test_dispatches_json_body_with_path_parameter(self):
		request = self._request(
			"/ceto/auth/customer/emailpass",
			"POST",
			json={"email": TEST_CUSTOMER, "password": TEST_CUSTOMER_PASSWORD},
		)
		login_manager = self._login_manager()
		previous_login_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = login_manager
		try:
			with self.set_request(request):
				response = ceto_router.dispatch(request)
		finally:
			frappe.local.login_manager = previous_login_manager

		self.assertEqual(response.status_code, 200)
		self.assertEqual(decode_customer_token(response.get_json()["token"])["sub"], TEST_CUSTOMER)

	def test_wrong_method_returns_medusa_405(self):
		response = ceto_router.dispatch(self._request("/ceto/auth/customer/emailpass", "GET"))
		self.assertEqual(response.status_code, 405)
		self.assertEqual(response.get_json(), {"type": "method_not_allowed", "message": "Method not allowed"})
		self.assertEqual(response.headers["Allow"], "POST")

	def test_unknown_ceto_route_returns_medusa_404(self):
		response = ceto_router.dispatch(self._request("/ceto/unknown", "GET"))
		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.get_json(), {"type": "not_found", "message": "Route not found"})

	def test_error_response_rolls_back_partial_writes(self):
		router = Router(prefix="/store")
		todo_name = f"ceto-router-rollback-{uuid4().hex}"

		@router.post("/orders", allow_guest=True)
		def create_order():
			frappe.get_doc(
				{"doctype": "ToDo", "name": todo_name, "description": "Must be rolled back"}
			).insert(ignore_permissions=True, set_name=todo_name)
			raise RuntimeError("failed after write")

		response = router.dispatch(self._request("/store/orders", "POST"))
		self.assertEqual(response.status_code, 500)
		self.assertFalse(frappe.db.exists("ToDo", todo_name))

	def test_protected_route_enforces_session_user(self):
		router = Router(prefix="/store")

		@router.get("/account")
		def account():
			return {"id": frappe.session.user}

		with self.set_user("Guest"):
			response = router.dispatch(self._request("/store/account", "GET"))
		self.assertEqual(response.status_code, 401)

		with self.set_user(TEST_CUSTOMER):
			response = router.dispatch(self._request("/store/account", "GET"))
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"id": TEST_CUSTOMER})

	def test_duplicate_route_is_rejected(self):
		router = Router(prefix="/store")
		router.get("/products")(lambda: None)
		with self.assertRaisesRegex(ValueError, "Duplicate route: GET /store/products"):
			router.get("/products")(lambda: None)

	def test_route_override_uses_external_route_key(self):
		router = Router(prefix="/ceto")

		@router.get("/store/products", allow_guest=True)
		def products():
			return {"source": "ceto"}

		with self.patch_hooks(
			{
				"ceto_route_overrides": {
					"GET /ceto/store/products": [
						"ceto.tests.routing.test_router.overridden_products"
					]
				}
			}
		):
			response = router.dispatch(self._request("/ceto/store/products", "GET"))
		self.assertEqual(response.get_json(), {"source": "override"})

	@staticmethod
	def _login_manager() -> LoginManager:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		return manager

	@staticmethod
	def _request(path: str, method: str, **kwargs) -> Request:
		kwargs.setdefault("environ_base", {"REMOTE_ADDR": "127.0.0.1"})
		return Request(EnvironBuilder(path=path, method=method, **kwargs).get_environ())
