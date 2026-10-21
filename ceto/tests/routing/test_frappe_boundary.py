"""The HTTP method boundary Frappe's own WSGI application imposes on Ceto.

``frappe.app.application`` forwards only GET/HEAD/POST to the website page
renderers and answers every other method with a 404 before any renderer runs,
so the pinned ``DELETE /store/carts/{id}/line-items/{line_id}`` contract is
unreachable through a Frappe front door and Ceto ships the compatibility
``POST …/delete`` twin (see ``CETO_CART_COMPAT_ROUTES``). These tests drive
the real WSGI application — not the Ceto router — so the boundary itself
stays pinned: if Frappe ever starts forwarding other methods, the DELETE
probe fails and the twin can be retired deliberately.
"""

import frappe
from frappe.app import application
from werkzeug.test import Client, TestResponse

from ceto.tests.utils import CetoTestSuite

LINE_ITEM_PATH = "/ceto/store/carts/cart_boundary/line-items/li_boundary"
TWIN_PATH = f"{LINE_ITEM_PATH}/delete"


class TestFrappeApplicationBoundary(CetoTestSuite):
	"""The requests here are answered by ``frappe.app.application`` itself."""

	def setUp(self) -> None:
		# A real request cycle ends with frappe.destroy, so the test runner's
		# thread-local state is captured here to rebuild it after the probes.
		self.site = frappe.local.site
		self.sites_path = frappe.local.sites_path
		self.conf = dict(frappe.conf)
		self.user = frappe.session.user

	def test_the_method_gate_refuses_delete_and_delivers_the_post_twin(self) -> None:
		"""A DELETE never reaches Ceto; the ``POST …/delete`` twin does.

		Both probes carry an unknown publishable key, so any request that
		reached the Ceto renderer would answer ``401 unauthorized`` from the
		scope guard. The DELETE answering ``404 not_found`` (normalized after
		the fact by the ``after_request`` hook, never by Ceto) proves Frappe
		refused it before any renderer ran; the twin answering ``401
		unauthorized`` proves Frappe delivered it to the Ceto page renderer
		and the twin route matched. The twin's behavioral parity with the
		pinned DELETE is pinned by the API boundary suite.
		"""
		try:
			refused = self._request("DELETE", LINE_ITEM_PATH)
			delivered = self._request("POST", TWIN_PATH)
		finally:
			self._restore_runner_state()

		self.assertEqual(refused.status_code, 404)
		self.assertEqual(refused.get_json()["type"], "not_found")

		self.assertEqual(delivered.status_code, 401)
		self.assertEqual(delivered.get_json()["type"], "unauthorized")

	def _request(self, method: str, path: str) -> TestResponse:
		# X-Frappe-Site-Name keeps site resolution off the Host header, and a
		# fresh client keeps each probe a complete worker request cycle.
		return Client(application).open(
			path,
			method=method,
			headers={"X-Frappe-Site-Name": self.site, "x-publishable-api-key": "pk_boundary_probe"},
		)

	def _restore_runner_state(self) -> None:
		"""Rebuild the site the test runner was using before these probes.

		Each real request ends with ``frappe.destroy``, so the connection,
		the conf overlays applied at import time and the user have to be
		restored for the suites that run after this one.
		"""
		frappe.init(site=self.site, sites_path=self.sites_path, force=True)
		frappe.connect()
		frappe.conf.update(self.conf)
		frappe.set_user(self.user)
