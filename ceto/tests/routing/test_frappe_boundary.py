"""The HTTP boundary Frappe's own WSGI application imposes on Ceto.

``frappe.app.application`` forwards only GET/HEAD/POST to the website page
renderers and answers every other method with a 404 before any renderer runs,
so the pinned ``DELETE /store/carts/{id}/line-items/{line_id}`` contract is
unreachable through a Frappe front door and Ceto ships the compatibility
``POST …/delete`` twin (see ``CETO_CART_COMPAT_ROUTES``). These tests drive
the real WSGI application — not the Ceto router — so the boundary itself
stays pinned: if Frappe ever starts forwarding other methods, the DELETE
probe fails and the twin can be retired deliberately.

The storefront calls the twin through the Medusa JS SDK's raw client, which
pins ``content-type: application/json`` on every call and stringifies the
body it is handed, so its removal request carries the explicit empty JSON
object ``{}`` as the body. The storefront-wire suite replays that exact
wire shape against the real application and expects a successful delete.
"""

import json

import frappe
from frappe.app import application
from werkzeug.test import Client, TestResponse

from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite

LINE_ITEM_PATH = "/ceto/store/carts/cart_boundary/line-items/li_boundary"
TWIN_PATH = f"{LINE_ITEM_PATH}/delete"

#: Publishable key the method-gate probes send; never configured, so any
#: request that reaches the Ceto renderer answers ``401 unauthorized``.
PROBE_KEY = "pk_boundary_probe"

#: Publishable key the storefront wire tests configure and send.
STOREFRONT_KEY = "pk_boundary_storefront"

#: The body the Medusa JS SDK client puts on the twin: it pins
#: ``content-type: application/json`` on every call and stringifies the body
#: it is handed, and Frappe refuses an empty JSON body, so the storefront
#: passes an explicit empty JSON object.
EMPTY_JSON_OBJECT = json.dumps({})

#: ``ceto_cart`` configuration the storefront wire requests run with; only the
#: ``before_request`` overlay below reads it, and ``setUp`` replaces it per
#: test.
storefront_cart_conf: dict = {}


def apply_storefront_cart_conf() -> None:
	"""``before_request`` overlay carrying test configuration into a cycle.

	A real request cycle rebuilds ``frappe.conf`` from the site config, so an
	in-process ``set_conf`` overlay never reaches it. Registered next to the
	real ``before_request`` hooks for the duration of one request, this applies
	the suite's ``ceto_cart`` configuration to the cycle's own conf copy —
	after ``frappe.init``, before any renderer runs.
	"""
	frappe.conf.update({"ceto_cart": storefront_cart_conf})


class FrappeApplicationSuite(CetoTestSuite):
	"""Shared plumbing for suites that drive ``frappe.app.application``."""

	def setUp(self) -> None:
		# A real request cycle ends with frappe.destroy, so the test runner's
		# thread-local state is captured here to rebuild it after the probes.
		self.site = frappe.local.site
		self.sites_path = frappe.local.sites_path
		self.conf = dict(frappe.conf)
		self.user = frappe.session.user

	def _request(
		self,
		method: str,
		path: str,
		*,
		body: str | None = None,
		publishable_key: str = PROBE_KEY,
		headers: dict[str, str] | None = None,
	) -> TestResponse:
		# X-Frappe-Site-Name keeps site resolution off the Host header, and a
		# fresh client keeps each probe a complete worker request cycle.
		merged: dict[str, str] = {
			"X-Frappe-Site-Name": self.site,
			"x-publishable-api-key": publishable_key,
		}
		if headers:
			merged.update(headers)
		return Client(application).open(
			path,
			method=method,
			data=body,
			content_type="application/json" if body is not None else None,
			headers=merged,
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


class TestFrappeApplicationBoundary(FrappeApplicationSuite):
	"""The requests here are answered by ``frappe.app.application`` itself."""

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


class TestFrappeApplicationStorefrontWire(FrappeApplicationSuite):
	"""The storefront's exact removal request, answered end-to-end.

	The store app deletes a cart line through the Medusa JS SDK's raw client:
	the twin path, the SDK's pinned ``content-type: application/json`` and
	``accept: application/json`` headers, and the explicit empty JSON object
	``{}`` as the body. Everything here — auth, ``make_form_dict`` body
	parsing, renderer delivery, deletion and the commit — runs inside the real
	application with a real cart, so the wire shape itself stays pinned: the
	twin must keep deleting through it.
	"""

	def setUp(self) -> None:
		super().setUp()
		with self.set_user("Administrator"):
			self.masters = CartTestData()
		# Every request cycle ends with frappe.destroy and reconnects, so the
		# masters have to be committed for those connections to see them.
		frappe.db.commit()
		storefront_cart_conf.clear()
		storefront_cart_conf.update(
			{
				**self.masters.configuration,
				"publishable_keys": {
					STOREFRONT_KEY: {"region_id": "reg_test", "sales_channel_id": "sc_test"}
				},
			}
		)
		# Captured while the runner state is alive: after a request cycle
		# frappe.get_hooks has no site to resolve the hooks against.
		self.before_request_hooks = list(frappe.get_hooks("before_request"))

	def test_the_storefront_wire_shape_deletes_the_line(self) -> None:
		try:
			cart_id = self._create_storefront_cart()
			line_id = self._add_storefront_line(cart_id)
			deleted = self._storefront_request(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items/{line_id}/delete",
				EMPTY_JSON_OBJECT,
			)
			retrieved = self._storefront_request("GET", f"/ceto/store/carts/{cart_id}?fields=id,items")
		finally:
			self._restore_runner_state()

		self.assertEqual(deleted.status_code, 200)
		self.assertEqual(
			deleted.get_json(),
			{"id": line_id, "object": "line-item", "deleted": True, "parent": cart_id},
		)

		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(retrieved.get_json()["cart"]["items"], [])

	def _storefront_request(self, method: str, path: str, body: str | None = None) -> TestResponse:
		# The cycle rebuilds frappe.conf, so the suite's configuration rides a
		# before_request overlay appended after the real hooks; the SDK pins
		# accept: application/json next to its content type on every call.
		overlay = f"{__name__}.apply_storefront_cart_conf"
		with self.patch_hooks({"before_request": [*self.before_request_hooks, overlay]}):
			return self._request(
				method,
				path,
				body=body,
				publishable_key=STOREFRONT_KEY,
				headers={"accept": "application/json"},
			)

	def _create_storefront_cart(self) -> str:
		created = self._storefront_request("POST", "/ceto/store/carts?fields=id", EMPTY_JSON_OBJECT)
		self.assertEqual(created.status_code, 200)
		return created.get_json()["cart"]["id"]

	def _add_storefront_line(self, cart_id: str) -> str:
		added = self._storefront_request(
			"POST",
			f"/ceto/store/carts/{cart_id}/line-items?fields=id,items",
			json.dumps({"variant_id": self.masters.item, "quantity": 1}),
		)
		self.assertEqual(added.status_code, 200)
		items = added.get_json()["cart"]["items"]
		self.assertEqual(len(items), 1)
		return items[-1]["id"]
