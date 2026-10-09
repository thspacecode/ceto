"""Store Region endpoints: guest-dispatchable reads of the commerce regions.

Pins the HTTP boundary on the test site: the pinned ``StoreRegionListResponse``
and ``StoreRegionResponse`` shapes, the publishable-key policy (required on
every read, validated at the boundary only — no customer session exists) and
the stable Medusa validation/errors: unknown query keys and out-of-bounds
pagination fail as ``400 invalid_data`` before anything resolves, and an
unknown or unservable region id masks as the same ``404 not_found``. Every
served region is cart-valid by construction: its ``currency_code`` is the
currency of the effective selling price list, the exact currency a cart in
that region prices in.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing import ceto_router
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data
from ceto.types.http.store.regions import StoreRegion

BROKEN_REGION = "reg_broken"
SERVABLE_REGION = "reg_api"


class TestRegionAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.price_list = settings.selling_price_list
		self.currency = frappe.db.get_value("Price List", self.price_list, "currency")
		self.configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"publishable_keys": {"pk_test": {}},
			"regions": {
				SERVABLE_REGION: {"company": self.company, "selling_price_list": self.price_list},
				BROKEN_REGION: {
					"company": self.company,
					"selling_price_list": self.price_list,
					"currency": "ZZZ",
				},
			},
		}

	def test_reads_are_guest_dispatchable(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			listed = self._dispatch("GET", "/ceto/store/regions")
			self.assertEqual(listed.status_code, 200)
			self.assertEqual(listed.get_json()["regions"][0]["id"], SERVABLE_REGION)

			retrieved = self._dispatch("GET", f"/ceto/store/regions/{SERVABLE_REGION}")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["region"]["id"], SERVABLE_REGION)

	def test_requires_a_configured_publishable_key(self):
		for publishable_key in (None, "pk_unknown"):
			with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
				for path in ("/ceto/store/regions", f"/ceto/store/regions/{SERVABLE_REGION}"):
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_serves_the_pinned_envelope_of_servable_regions(self):
		with self.set_conf(ceto_cart=self.configuration):
			response = self._dispatch("GET", "/ceto/store/regions")
		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"regions", "count", "offset", "limit"})
		self.assertEqual(body["count"], 1)
		self.assertEqual(body["offset"], 0)
		self.assertEqual(body["limit"], 20)
		(region,) = body["regions"]
		self.assertEqual(set(region), set(StoreRegion.model_fields))
		self.assertEqual(region["id"], SERVABLE_REGION)
		self.assertEqual(region["name"], SERVABLE_REGION)
		# Cart-valid by construction: the served currency is the price list
		# currency, the exact currency a cart in this region prices in.
		self.assertEqual(region["currency_code"], (self.currency or "").lower())
		self.assertNotIn(BROKEN_REGION, [entry["id"] for entry in body["regions"]])

	def test_list_pagination_is_validated_not_clamped(self):
		with self.set_conf(ceto_cart=self.configuration):
			page = self._dispatch("GET", "/ceto/store/regions?offset=1&limit=1")
			self.assertEqual(page.status_code, 200)
			self.assertEqual(page.get_json()["regions"], [])
			self.assertEqual(page.get_json()["offset"], 1)
			self.assertEqual(page.get_json()["limit"], 1)
			self.assertEqual(page.get_json()["count"], 1)

			for query in ("limit=101", "limit=-1", "offset=-1", "q=region"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/regions?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_detail_matches_the_list_projection(self):
		with self.set_conf(ceto_cart=self.configuration):
			listed = self._dispatch("GET", "/ceto/store/regions")
			retrieved = self._dispatch("GET", f"/ceto/store/regions/{SERVABLE_REGION}")
		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"region"})
		self.assertEqual(retrieved.get_json()["region"], listed.get_json()["regions"][0])

	def test_unknown_and_unservable_ids_mask_as_not_found(self):
		with self.set_conf(ceto_cart=self.configuration), self.set_user("Guest"):
			for region_id in ("reg_unknown", BROKEN_REGION):
				with self.subTest(region_id=region_id):
					response = self._dispatch("GET", f"/ceto/store/regions/{region_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_detail_refuses_every_query_key(self):
		with self.set_conf(ceto_cart=self.configuration):
			response = self._dispatch("GET", f"/ceto/store/regions/{SERVABLE_REGION}?fields=id,currency_code")
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

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
