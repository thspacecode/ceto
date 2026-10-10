"""Store Product Category endpoints: guest-dispatchable reads of the published tree.

Pins the HTTP boundary on the test site: the pinned ``StoreProductCategoryListResponse``
and ``StoreProductCategoryResponse`` shapes, the publishable-key policy (required on
every read, validated at the boundary only — no customer session exists), the
stable Medusa validation/errors — unknown query keys, the tree expansion flags,
the upstream filter/sort/field surfaces and out-of-bounds pagination all fail
as ``400 invalid_data`` before anything resolves, an unknown or unpublished id
masks as ``404 not_found``, and with no storefront roots configured the routes
serve an empty page instead of the ERPNext default tree — and that the
endpoints are Ceto-router-only, never whitelisted RPC.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.routing import ceto_router
from ceto.services.catalog.product_categories import category_public_id
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.product_categories import StoreProductCategory

PUBLISHABLE_KEYS = {"pk_test": {}}

ROOT = "API Storefront Root"
APPAREL = "API Storefront Apparel"
T_SHIRTS = "API Storefront T-Shirts"
OUTSIDE = "API Storefront Outside"


class TestProductCategoryAPI(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(APPAREL, parent=ROOT, is_group=True)
		self.fixtures.item_group(T_SHIRTS, parent=APPAREL)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self) -> Iterator[None]:
		"""Scope the demo storefront boundary: the key store and one root."""
		with (
			self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}),
			self.set_conf(ceto_catalog={"category_roots": [ROOT]}),
		):
			yield

	def test_reads_are_guest_dispatchable(self):
		with self.publish(), self.set_user("Guest"):
			listed = self._dispatch("GET", "/ceto/store/product-categories")
			self.assertEqual(listed.status_code, 200)
			self.assertEqual(listed.get_json()["count"], 3)

			retrieved = self._dispatch(
				"GET", f"/ceto/store/product-categories/{category_public_id(T_SHIRTS)}"
			)
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["product_category"]["name"], T_SHIRTS)

	def test_requires_a_configured_publishable_key(self):
		for publishable_key in (None, "pk_unknown"):
			with self.publish(), self.set_user("Guest"):
				for path in (
					"/ceto/store/product-categories",
					f"/ceto/store/product-categories/{category_public_id(APPAREL)}",
				):
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_list_serves_the_pinned_envelope_of_the_published_tree(self):
		with self.publish():
			response = self._dispatch("GET", "/ceto/store/product-categories")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"product_categories", "count", "offset", "limit"})
		self.assertEqual((body["offset"], body["limit"]), (0, 50))
		self.assertEqual([entry["name"] for entry in body["product_categories"]], [ROOT, APPAREL, T_SHIRTS])
		entry = body["product_categories"][2]
		self.assertEqual(set(entry), set(StoreProductCategory.model_fields))
		self.assertEqual(entry["id"], category_public_id(T_SHIRTS))
		self.assertTrue(entry["id"].startswith("pcat_"))
		self.assertEqual(entry["handle"], "api-storefront-t-shirts")
		self.assertEqual(entry["parent_category_id"], category_public_id(APPAREL))
		# The served timestamps are the real record timestamps.
		self.assertIsNotNone(entry["created_at"])
		self.assertIsNotNone(entry["updated_at"])
		self.assertIsNone(entry["rank"])
		self.assertIsNone(entry["deleted_at"])
		self.assertEqual(entry["category_children"], [])

	def test_without_roots_configuration_the_list_is_empty(self):
		with (
			self.set_conf(ceto_cart={"publishable_keys": PUBLISHABLE_KEYS}),
			self.set_conf(ceto_catalog=None),
		):
			response = self._dispatch("GET", "/ceto/store/product-categories")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(
			response.get_json(), {"product_categories": [], "count": 0, "offset": 0, "limit": 50}
		)

	def test_list_pagination_is_validated_not_clamped(self):
		with self.publish():
			page = self._dispatch("GET", "/ceto/store/product-categories?offset=1&limit=1")
			self.assertEqual(page.status_code, 200)
			self.assertEqual(page.get_json()["offset"], 1)
			self.assertEqual(page.get_json()["limit"], 1)
			self.assertEqual(page.get_json()["count"], 3)

			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"q=apparel",
				"handle=api-storefront-apparel",
				"name=Apparel",
				"parent_category_id=pcat_1",
				"is_active=true",
				"is_internal=true",
				"external_id=erp-1",
				"order=handle",
				"fields=id,handle",
				"created_at[after]=2026-01-01",
				"$or[0][handle]=api-storefront-apparel",
				"include_descendants_tree=true",
				"include_ancestors_tree=true",
				"limit=1.5",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/product-categories?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_detail_matches_the_list_projection(self):
		with self.publish():
			listed = self._dispatch("GET", "/ceto/store/product-categories?limit=100")
			retrieved = self._dispatch("GET", f"/ceto/store/product-categories/{category_public_id(APPAREL)}")

		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"product_category"})
		listed_entry = next(
			entry
			for entry in listed.get_json()["product_categories"]
			if entry["id"] == category_public_id(APPAREL)
		)
		self.assertEqual(retrieved.get_json()["product_category"], listed_entry)

	def test_unknown_malformed_and_unpublished_ids_mask_as_not_found(self):
		with self.publish(), self.set_user("Guest"):
			for category_id in (
				"pcat_" + "0" * 32,
				"not-a-category",
				"cat_123",
				category_public_id(OUTSIDE),
				category_public_id("All Item Groups"),
			):
				with self.subTest(category_id=category_id):
					response = self._dispatch("GET", f"/ceto/store/product-categories/{category_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_detail_refuses_every_query_key(self):
		with self.publish():
			for query in ("fields=id,handle", "include_descendants_tree=true", "limit=1"):
				with self.subTest(query=query):
					response = self._dispatch(
						"GET", f"/ceto/store/product-categories/{category_public_id(APPAREL)}?{query}"
					)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_endpoints_are_not_whitelisted(self):
		from ceto.api.store.product_categories import list_product_categories, retrieve_product_category

		for endpoint in (list_product_categories, retrieve_product_category):
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
