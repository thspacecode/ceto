"""Store Product Tag endpoints: guest-dispatchable reads of the served tags.

Pins the HTTP boundary on the test site: the pinned
``StoreProductTagListResponse`` and ``StoreProductTagResponse`` shapes, the
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
from ceto.services.catalog.product_tags import ProductTagDirectory, tag_public_id
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.product_tags import StoreProductTag

PUBLISHABLE_KEYS = {"pk_test": {}}


class TestProductTagAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()

	def test_reads_are_guest_dispatchable(self):
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Guest Tag")

		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
			listed = self._dispatch("GET", "/ceto/store/product-tags")
			self.assertEqual(listed.status_code, 200)

			retrieved = self._dispatch("GET", f"/ceto/store/product-tags/{tag_public_id(value)}")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["product_tag"]["value"], value)

	def test_requires_a_configured_publishable_key(self):
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Keyed Tag")
		detail = f"/ceto/store/product-tags/{tag_public_id(value)}"
		for publishable_key in (None, "pk_unknown"):
			with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
				for path in ("/ceto/store/product-tags", detail):
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_serves_the_pinned_envelope_ordered_by_value(self):
		# The pinned order (Recorded Decision 6) is the value ascending: the
		# alphabetically first served value must lead the page, whatever its
		# creation time.
		self.fixtures.item_tag(self.fixtures.item(), "Dev Zulu Tag")
		self.fixtures.item_tag(self.fixtures.item(), "Dev Alpha Tag")

		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			response = self._dispatch("GET", "/ceto/store/product-tags")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"product_tags", "count", "offset", "limit"})
		self.assertEqual(body["offset"], 0)
		self.assertEqual(body["limit"], 50)
		served = ProductTagDirectory().served_values()
		self.assertEqual(body["count"], len(served))
		values = [entry["value"] for entry in body["product_tags"]]
		self.assertEqual(values, sorted(values))
		self.assertIn("Dev Alpha Tag", values)
		self.assertIn("Dev Zulu Tag", values)
		self.assertLess(values.index("Dev Alpha Tag"), values.index("Dev Zulu Tag"))
		entry = next(entry for entry in body["product_tags"] if entry["value"] == "Dev Alpha Tag")
		self.assertEqual(set(entry), set(StoreProductTag.model_fields))
		# A tag is a projection of other records' tags: no timestamps are
		# ever fabricated for it (Recorded Decision 8).
		self.assertIsNone(entry["created_at"])
		self.assertIsNone(entry["updated_at"])
		self.assertIsNone(entry["deleted_at"])

	def test_list_pagination_is_validated_not_clamped(self):
		self.fixtures.item_tag(self.fixtures.item(), "Dev Paged Tag")
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			page = self._dispatch("GET", "/ceto/store/product-tags?offset=1&limit=1")
			self.assertEqual(page.status_code, 200)
			self.assertEqual(page.get_json()["offset"], 1)
			self.assertEqual(page.get_json()["limit"], 1)
			self.assertEqual(page.get_json()["count"], len(ProductTagDirectory().served_values()))

			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"q=summer",
				"value=Summer",
				"id=ptag_1",
				"external_id=erp-1",
				"order=value",
				"fields=id,value",
				"created_at[after]=2026-01-01",
				"$or[0][value]=Summer",
				"limit=1.5",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/product-tags?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_detail_matches_the_list_projection(self):
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Parity Tag")
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			listed = self._dispatch("GET", "/ceto/store/product-tags?limit=100")
			retrieved = self._dispatch("GET", f"/ceto/store/product-tags/{tag_public_id(value)}")
		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"product_tag"})
		listed_entry = next(entry for entry in listed.get_json()["product_tags"] if entry["value"] == value)
		self.assertEqual(retrieved.get_json()["product_tag"], listed_entry)

	def test_unknown_and_malformed_ids_mask_as_not_found(self):
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}), self.set_user("Guest"):
			for tag_id in ("ptag_" + "0" * 32, "not-a-tag", "tag_123"):
				with self.subTest(tag_id=tag_id):
					response = self._dispatch("GET", f"/ceto/store/product-tags/{tag_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_detail_refuses_every_query_key(self):
		value = self.fixtures.item_tag(self.fixtures.item(), "Dev Strict Tag")
		with self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}):
			response = self._dispatch(
				"GET", f"/ceto/store/product-tags/{tag_public_id(value)}?fields=id,value"
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_endpoints_are_not_whitelisted(self):
		from ceto.api.store.product_tags import list_product_tags, retrieve_product_tag

		for endpoint in (list_product_tags, retrieve_product_tag):
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
