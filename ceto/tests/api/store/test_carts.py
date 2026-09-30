import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite


class TestCartAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.configuration = {
			**self.masters.configuration,
			"publishable_keys": {"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"}},
		}

	def test_guest_create_retrieve_and_update(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			created = self._dispatch(
				"POST",
				"/ceto/store/carts?fields=id,email,currency_code",
				{"email": "guest@example.com"},
			)
			self.assertEqual(created.status_code, 200)
			created_cart = created.get_json()["cart"]
			self.assertEqual(set(created_cart), {"id", "email", "currency_code"})
			cart_id = created_cart["id"]

			retrieved = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,email")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["cart"]["email"], "guest@example.com")

			updated = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}?fields=id,email,metadata",
				{"email": "new@example.com", "metadata": {"campaign": "fall"}},
			)
			self.assertEqual(updated.status_code, 200)
			self.assertEqual(
				updated.get_json()["cart"],
				{
					"id": cart_id,
					"email": "new@example.com",
					"metadata": {"campaign": "fall"},
				},
			)

	def test_invalid_payload_uses_medusa_error_shape(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/carts", {"unknown": True})
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_requires_a_configured_publishable_key(self) -> None:
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			response = self._dispatch("POST", "/ceto/store/carts", {}, publishable_key=None)
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.get_json()["type"], "unauthorized")

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		publishable_key: str | None = "pk_test",
	):
		headers = {"x-publishable-api-key": publishable_key} if publishable_key else None
		builder = EnvironBuilder(
			path=path,
			method=method,
			data=json.dumps(payload) if payload is not None else None,
			content_type="application/json" if payload is not None else None,
			headers=headers,
			environ_base={"REMOTE_ADDR": "127.0.0.1"},
		)
		request = Request(builder.get_environ())
		with self.set_request(request):
			return ceto_router.dispatch(request)
