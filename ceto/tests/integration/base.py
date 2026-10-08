"""Shared boundary kit for the integration journeys.

The integration modules dispatch whole requests through the real router on
the test site; this module is the minimal kit they share: the storefront
``ceto_cart`` configuration (the bootstrap commerce masters plus one scoped
publishable key), the request/dispatch pair that mirrors production's
two-stage authentication — Frappe's ``auth_hooks`` runner, then the router —
and the ``LoginManager`` stub the emailpass credential flow needs on a test
site (the provider drives Frappe's real login machinery against it, exactly
like ``ceto.tests.api.auth`` does).
"""

import json

import frappe
from frappe.auth import LoginManager
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.auth.tokens import authenticate_bearer_token
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT
from ceto.tests.utils import CetoTestSuite

PUBLISHABLE_KEY = "pk_test"


class IntegrationTestBase(CetoTestSuite):
	"""The dispatched-router boundary fixtures shared by the journeys."""

	def setUp(self) -> None:
		# Test fixture setup requires an explicit privileged baseline; each
		# request below still exercises production authentication boundaries.
		frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
		self.masters = CartTestData()
		self._previous_conf = frappe.conf.get("ceto_cart")
		frappe.conf["ceto_cart"] = {
			**self.masters.configuration,
			"publishable_keys": {
				PUBLISHABLE_KEY: {
					"region_id": self.masters.configuration["default_region_id"],
					"sales_channel_id": self.masters.configuration["default_sales_channel_id"],
				}
			},
		}
		# The journeys register identities; lift Frappe's user-creation
		# throttle like every other user-creating suite.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = THROTTLE_USER_LIMIT

	def tearDown(self) -> None:
		if self._previous_conf is None:
			frappe.conf.pop("ceto_cart", None)
		else:
			frappe.conf["ceto_cart"] = self._previous_conf
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _dispatch(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		token: str | None = None,
		publishable_key: str | None = PUBLISHABLE_KEY,
	):
		request = self._request(method, path, payload, token=token, publishable_key=publishable_key)
		with self.set_request(request):
			return ceto_router.dispatch(request)

	def _dispatch_with_hook(
		self,
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		token: str,
		publishable_key: str | None = PUBLISHABLE_KEY,
	):
		"""Dispatch like production: the auth hook runs before the router.

		``auth_hooks`` authenticates ``auth``-purpose bearer requests by
		setting the session user; a refused token raises before the router
		runs (Frappe itself renders the 401).
		"""
		request = self._request(method, path, payload, token=token, publishable_key=publishable_key)
		with self.set_request(request), self.set_user("Guest"):
			authenticate_bearer_token()
			return ceto_router.dispatch(request)

	def _dispatch_authentication(self, path: str, payload: dict):
		"""Dispatch a credential auth route with its LoginManager stub."""
		request = self._request("POST", path, payload, publishable_key=None)
		manager = self._login_manager()
		previous_manager = getattr(frappe.local, "login_manager", None)
		frappe.local.login_manager = manager
		try:
			with self.set_request(request):
				return ceto_router.dispatch(request), manager
		finally:
			frappe.local.login_manager = previous_manager

	@staticmethod
	def _request(
		method: str,
		path: str,
		payload: dict | None = None,
		*,
		token: str | None = None,
		publishable_key: str | None = PUBLISHABLE_KEY,
	) -> Request:
		headers = {}
		if publishable_key:
			headers["x-publishable-api-key"] = publishable_key
		if token:
			headers["Authorization"] = f"Bearer {token}"
		return Request(
			EnvironBuilder(
				path=path,
				method=method,
				data=json.dumps(payload) if payload is not None else None,
				content_type="application/json" if payload is not None else None,
				headers=headers or None,
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			).get_environ()
		)

	@staticmethod
	def _login_manager() -> LoginManager:
		manager = LoginManager.__new__(LoginManager)
		manager.user = None
		manager.info = None
		manager.full_name = None
		manager.user_type = None
		manager.resume = False
		return manager

	def _assert_error(self, response, status: int, error_type: str) -> dict:
		"""Assert the pinned Ceto error body for one refused request."""
		self.assertEqual(status, response.status_code, response.get_json())
		body = response.get_json()
		self.assertEqual(error_type, body.get("type"))
		return body
