"""Store Product Type endpoints: guest-dispatchable reads of the stored taxonomy.

Pins the HTTP boundary on the test site: the pinned
``StoreProductTypeListResponse`` and ``StoreProductTypeResponse`` shapes, the
publishable-key policy (required on every read, validated at the boundary
only — no customer session exists), the stable Medusa validation/errors —
unknown query keys, the upstream filter/sort/field surfaces and out-of-bounds
pagination all fail as ``400 invalid_data`` before anything resolves, and an
unknown id masks as ``404 not_found`` — and that the endpoints are
Ceto-router-only, never whitelisted RPC.
"""

import json

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.product_types import StoreProductType

PUBLISHABLE_KEYS = {"pk_test": {}}


class TestProductTypeAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	def test_reads_are_guest_dispatchable(self):
		stored = self.fixtures.product_type()
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
			listed = self._dispatch("GET", "/ceto/store/product-types")
			self.assertEqual(listed.status_code, 200)

			retrieved = self._dispatch("GET", f"/ceto/store/product-types/{stored.type_id}")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["product_type"]["id"], stored.type_id)

	def test_requires_a_configured_publishable_key(self):
		stored = self.fixtures.product_type()
		for publishable_key in (None, "pk_unknown"):
			with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
				for path in ("/ceto/store/product-types", f"/ceto/store/product-types/{stored.type_id}"):
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_serves_the_pinned_envelope_ordered_by_value(self):
		# The pinned order (Recorded Decision 6) is the value ascending: the
		# alphabetically first stored value must lead the page, whatever its
		# creation time.
		late = self.fixtures.product_type(value="Dev Zulu Type")
		early = self.fixtures.product_type(value="Dev Alpha Type")

		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			response = self._dispatch("GET", "/ceto/store/product-types")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"product_types", "count", "offset", "limit"})
		self.assertEqual(body["offset"], 0)
		self.assertEqual(body["limit"], 50)
		self.assertEqual(body["count"], frappe.db.count("Ceto Product Type"))
		values = [entry["value"] for entry in body["product_types"]]
		self.assertEqual(values, sorted(values))
		self.assertIn(early.type_id, [entry["id"] for entry in body["product_types"]])
		self.assertIn(late.type_id, [entry["id"] for entry in body["product_types"]])
		self.assertLess(values.index("Dev Alpha Type"), values.index("Dev Zulu Type"))
		entry = next(entry for entry in body["product_types"] if entry["id"] == early.type_id)
		self.assertEqual(set(entry), set(StoreProductType.model_fields))
		# The storage slice serves the real record timestamps.
		self.assertIsNotNone(entry["created_at"])
		self.assertIsNotNone(entry["updated_at"])
		self.assertIsNone(entry["deleted_at"])

	def test_list_pagination_is_validated_not_clamped(self):
		self.fixtures.product_type()
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			page = self._dispatch("GET", "/ceto/store/product-types?offset=1&limit=1")
			self.assertEqual(page.status_code, 200)
			self.assertEqual(page.get_json()["offset"], 1)
			self.assertEqual(page.get_json()["limit"], 1)
			self.assertEqual(page.get_json()["count"], frappe.db.count("Ceto Product Type"))

			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"q=physical",
				"value=Physical",
				"external_id=ext-type-1",
				"order=value",
				"fields=id,value",
				"updated_at[after]=2026-01-01",
				"$and[0][value]=Physical",
				"limit=1.5",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/product-types?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_detail_matches_the_list_projection(self):
		stored = self.fixtures.product_type(metadata={"tier": "core"})
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			listed = self._dispatch("GET", "/ceto/store/product-types?limit=100")
			retrieved = self._dispatch("GET", f"/ceto/store/product-types/{stored.type_id}")
		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"product_type"})
		listed_entry = next(
			entry for entry in listed.get_json()["product_types"] if entry["id"] == stored.type_id
		)
		self.assertEqual(retrieved.get_json()["product_type"], listed_entry)

	def test_unknown_and_malformed_ids_mask_as_not_found(self):
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
			for type_id in ("ptyp_" + "0" * 32, "not-a-type", "type_123"):
				with self.subTest(type_id=type_id):
					response = self._dispatch("GET", f"/ceto/store/product-types/{type_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_detail_refuses_every_query_key(self):
		stored = self.fixtures.product_type()
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			response = self._dispatch("GET", f"/ceto/store/product-types/{stored.type_id}?fields=id,value")
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_endpoints_are_not_whitelisted(self):
		from ceto.api.store.product_types import list_product_types, retrieve_product_type

		for endpoint in (list_product_types, retrieve_product_type):
			with self.subTest(endpoint=endpoint.__name__):
				self.assertNotIn(endpoint, frappe.whitelisted)
				self.assertFalse(hasattr(endpoint, "is_whitelisted"))

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
