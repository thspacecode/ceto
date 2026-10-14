"""Store Product endpoints: guest-dispatchable reads of the published assortment.

Pins the HTTP boundary on the test site: the five pinned response shapes
(``StoreProductListResponse`` / ``StoreProductResponse`` /
``StoreProductVariantListResponse`` / ``StoreProductOptionListResponse`` /
``StoreProductOptionResponse``), the publishable-key policy (required on
every read, validated at the boundary only — no customer session exists),
the stable Medusa validation/errors — unknown query keys, the pricing
context keys and out-of-bounds pagination all fail as ``400 invalid_data``
before anything resolves, an unknown or unpublished id masks as ``404
not_found`` — the page echo over the whole assortment, the detail parity
with the list projection, the region-aware ``calculated_price`` and that
the endpoints are Ceto-router-only, never whitelisted RPC, and remain
overridable through the shared ``ceto_route_overrides`` hook.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import ceto.api.routes
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing import ceto_router
from ceto.services.catalog.products import option_public_id, product_public_id
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data
from ceto.types.http.store.products import (
	StoreProduct,
	StoreProductOption,
	StoreProductVariant,
)

PUBLISHABLE_KEYS = {"pk_test": {}}

ROOT = "API Products Root"
IN_ROOT = "API Products Apparel"
OUTSIDE = "API Products Outside"

PRODUCT_PATHS = (
	"/ceto/store/products",
	"/ceto/store/products/prod_some_product",
	"/ceto/store/product-variants",
	"/ceto/store/product-options",
	"/ceto/store/product-options/opt_some_option",
)


def overridden_products() -> dict[str, str]:
	"""The registered-key override the boundary suite dispatches through."""
	return {"source": "override"}


class ProductAPITestSuite(CetoTestSuite):
	"""Shared anchors: the storefront roots and, when priced, the cart ones."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(IN_ROOT, parent=ROOT)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def storefront(self, *, priced: bool = False) -> Iterator[None]:
		"""Scope the demo storefront boundary: the key store and one root.

		``priced`` adds the cart anchors the pricing authority resolves, so
		a presented ``region_id`` prices exactly like a configured
		deployment would.
		"""
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		ceto_cart: dict = {"publishable_keys": PUBLISHABLE_KEYS}
		if priced:
			ceto_cart.update(
				{
					"guest_customer": frappe.db.get_value(
						"Customer", {"customer_name": settings.guest_customer_name}
					),
					"company": resolve_company(settings),
					"selling_price_list": settings.selling_price_list,
				}
			)
		with self.set_conf(ceto_catalog={"category_roots": [ROOT]}, ceto_cart=ceto_cart):
			yield

	def published_item(self, **overrides):
		overrides.setdefault("item_group", IN_ROOT)
		return self.fixtures.item(**overrides)

	def family(self, head_code: str):
		"""Mint one published single-attribute family with one variant."""
		attribute = self.fixtures.item_attribute("Black", "Red")
		head = self.fixtures.template_item(
			item_code=head_code, item_group=IN_ROOT, attributes=[{"attribute": attribute}]
		)
		self.fixtures.variant_item(head, item_code=f"{head_code}-BLACK")
		return head, attribute

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


class TestProductAPIBoundary(ProductAPITestSuite):
	"""The publishable-key boundary and the dispatch surface itself."""

	def test_reads_are_guest_dispatchable(self):
		head, _ = self.family("DEV-API-GUEST")
		with self.storefront(), self.set_user("Guest"):
			for path in (
				"/ceto/store/products",
				"/ceto/store/product-variants",
				"/ceto/store/product-options",
			):
				with self.subTest(path=path):
					listed = self._dispatch("GET", path)
					self.assertEqual(listed.status_code, 200)
					self.assertGreaterEqual(listed.get_json()["count"], 1)

			retrieved = self._dispatch("GET", f"/ceto/store/products/{product_public_id(head.name)}")
			self.assertEqual(retrieved.status_code, 200)
			self.assertEqual(retrieved.get_json()["product"]["id"], product_public_id(head.name))

			options = self._dispatch("GET", "/ceto/store/product-options")
			retrieved_option = self._dispatch(
				"GET", f"/ceto/store/product-options/{options.get_json()['product_options'][0]['id']}"
			)
			self.assertEqual(retrieved_option.status_code, 200)

	def test_requires_a_configured_publishable_key(self):
		for publishable_key in (None, "pk_unknown"):
			with self.storefront(), self.set_user("Guest"):
				for path in PRODUCT_PATHS:
					with self.subTest(publishable_key=publishable_key, path=path):
						response = self._dispatch("GET", path, publishable_key=publishable_key)
						self.assertEqual(response.status_code, 401)
						self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_endpoints_are_not_whitelisted(self):
		from ceto.api.store.products import (
			list_product_options,
			list_product_variants,
			list_products,
			retrieve_product,
			retrieve_product_option,
		)

		for endpoint in (
			list_products,
			retrieve_product,
			list_product_variants,
			list_product_options,
			retrieve_product_option,
		):
			with self.subTest(endpoint=endpoint.__name__):
				self.assertNotIn(endpoint, frappe.whitelisted)
				self.assertFalse(hasattr(endpoint, "is_whitelisted"))

	def test_route_override_serves_the_registered_key(self):
		with (
			self.storefront(),
			self.patch_hooks(
				{
					"ceto_route_overrides": {
						"GET /ceto/store/products": ["ceto.tests.api.store.test_products.overridden_products"]
					}
				}
			),
		):
			response = self._dispatch("GET", "/ceto/store/products")

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.get_json(), {"source": "override"})


class TestProductQueryValidation(ProductAPITestSuite):
	"""The pinned query contracts refuse everything they do not pin."""

	def test_the_product_list_rejects_unknown_keys_and_bad_pagination(self):
		with self.storefront():
			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"limit=1.5",
				"q=sock",
				"handle=dev-sock",
				"title=Dev Sock",
				"is_giftcard=true",
				"status=published",
				"category_id=pcat_1",
				"order=handle",
				"fields=id,handle",
				"created_at[after]=2026-01-01",
				"$or[0][handle]=dev-sock",
				"variants[sku]=DEV-1",
				"locale=en-US",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/products?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_the_product_list_accepts_only_the_pinned_pricing_context(self):
		with self.storefront(priced=True):
			accepted = self._dispatch("GET", "/ceto/store/products?region_id=reg_test")
			self.assertEqual(accepted.status_code, 200)

			for query in ("country_code=US", "province=CA", "cart_id=cart_1"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/products?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_the_variants_list_rejects_unknown_keys_and_bad_pagination(self):
		with self.storefront():
			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"sku=DEV-1",
				"product_id=prod_1",
				"options[attribute]=Colour",
				"order=sku",
				"fields=id,sku",
				"country_code=US",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/product-variants?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_the_options_list_rejects_unknown_keys_and_any_pricing_context(self):
		with self.storefront(priced=True):
			for query in (
				"limit=101",
				"limit=-1",
				"offset=-1",
				"title=Colour",
				"order=title",
				"fields=id,title",
				"region_id=reg_test",
			):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/product-options?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_the_product_detail_accepts_only_the_pricing_context(self):
		head, _ = self.family("DEV-API-DETAILQ")
		detail = f"/ceto/store/products/{product_public_id(head.name)}"
		with self.storefront(priced=True):
			accepted = self._dispatch("GET", f"{detail}?region_id=reg_test")
			self.assertEqual(accepted.status_code, 200)

			for query in ("fields=id,handle", "country_code=US", "cart_id=cart_1", "limit=1"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"{detail}?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_the_option_detail_refuses_every_query_key(self):
		head, attribute = self.family("DEV-API-OPTQ")
		detail = f"/ceto/store/product-options/{option_public_id(head.name, attribute)}"
		with self.storefront(priced=True):
			for query in ("fields=id,title", "limit=1", "region_id=reg_test"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"{detail}?{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")


class TestProductAPIPagination(ProductAPITestSuite):
	"""The envelope echoes the effective page over the whole served set."""

	def test_the_product_list_serves_the_pinned_envelope_and_page(self):
		for suffix in "ABC":
			self.published_item(item_code=f"DEV-API-PAGE-{suffix}", item_name=f"Dev API Page {suffix}")

		with self.storefront():
			whole = self._dispatch("GET", "/ceto/store/products")
			page = self._dispatch("GET", "/ceto/store/products?offset=1&limit=1")
			beyond = self._dispatch("GET", "/ceto/store/products?offset=10")

		self.assertEqual(whole.status_code, 200)
		body = whole.get_json()
		self.assertEqual(set(body), {"products", "count", "offset", "limit"})
		self.assertEqual((body["offset"], body["limit"], body["count"]), (0, 50, 3))
		entry = body["products"][0]
		self.assertEqual(set(entry), set(StoreProduct.model_fields))
		self.assertEqual(
			[product["handle"] for product in body["products"]],
			["dev-api-page-a", "dev-api-page-b", "dev-api-page-c"],
		)
		self.assertEqual([product["handle"] for product in page.get_json()["products"]], ["dev-api-page-b"])
		self.assertEqual((page.get_json()["count"], page.get_json()["offset"]), (3, 1))
		self.assertEqual((beyond.get_json()["products"], beyond.get_json()["count"]), ([], 3))

	def test_the_variants_surface_serves_the_pinned_envelope_and_page(self):
		first = self.published_item(item_code="DEV-API-VAR-A", item_name="Dev API Var A")
		second = self.published_item(item_code="DEV-API-VAR-B", item_name="Dev API Var B")

		with self.storefront():
			whole = self._dispatch("GET", "/ceto/store/product-variants")
			page = self._dispatch("GET", "/ceto/store/product-variants?offset=1&limit=1")

		body = whole.get_json()
		self.assertEqual(set(body), {"variants", "count", "offset", "limit"})
		self.assertEqual((body["offset"], body["limit"], body["count"]), (0, 20, 2))
		self.assertEqual([variant["sku"] for variant in body["variants"]], [first.name, second.name])
		entry = body["variants"][0]
		self.assertEqual(set(entry), set(StoreProductVariant.model_fields))
		self.assertEqual([variant["sku"] for variant in page.get_json()["variants"]], [second.name])

	def test_the_options_surface_serves_the_pinned_envelope_and_page(self):
		self.family("DEV-API-OPT-A")
		self.family("DEV-API-OPT-B")

		with self.storefront():
			whole = self._dispatch("GET", "/ceto/store/product-options")
			page = self._dispatch("GET", "/ceto/store/product-options?offset=1&limit=1")

		body = whole.get_json()
		self.assertEqual(set(body), {"product_options", "count", "offset", "limit"})
		self.assertEqual((body["offset"], body["limit"], body["count"]), (0, 50, 2))
		entry = body["product_options"][0]
		self.assertEqual(set(entry), set(StoreProductOption.model_fields))
		self.assertEqual(
			[option["id"] for option in page.get_json()["product_options"]],
			[body["product_options"][1]["id"]],
		)


class TestProductDetailParity(ProductAPITestSuite):
	"""Detail answers the identical projection the list serves."""

	def test_the_product_detail_matches_the_list_projection(self):
		head, _ = self.family("DEV-API-PARITY")
		self.published_item(item_code="DEV-API-PARITY-SOLO", item_name="Dev API Parity Solo")

		with self.storefront():
			listed = self._dispatch("GET", "/ceto/store/products?limit=100")
			retrieved = self._dispatch("GET", f"/ceto/store/products/{product_public_id(head.name)}")

		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"product"})
		listed_entry = next(
			entry for entry in listed.get_json()["products"] if entry["id"] == product_public_id(head.name)
		)
		self.assertEqual(retrieved.get_json()["product"], listed_entry)
		# The family serves its variant and its option, the standalone its own.
		self.assertEqual(len(listed_entry["variants"]), 1)
		self.assertEqual(listed_entry["variants"][0]["sku"], f"{head.name}-BLACK")
		self.assertEqual(len(listed_entry["options"]), 1)

	def test_the_option_detail_matches_the_list_projection(self):
		head, attribute = self.family("DEV-API-OPTPARITY")
		self.fixtures.variant_item(head, attribute_value="Red", item_code=f"{head.name}-RED")

		with self.storefront():
			listed = self._dispatch("GET", "/ceto/store/product-options")
			retrieved = self._dispatch(
				"GET", f"/ceto/store/product-options/{option_public_id(head.name, attribute)}"
			)

		self.assertEqual(retrieved.status_code, 200)
		self.assertEqual(set(retrieved.get_json()), {"product_option"})
		self.assertEqual(retrieved.get_json()["product_option"], listed.get_json()["product_options"][0])
		option = retrieved.get_json()["product_option"]
		self.assertEqual(option["title"], attribute)
		self.assertEqual([value["value"] for value in option["values"]], ["Black", "Red"])
		self.assertEqual({value["option_id"] for value in option["values"]}, {option["id"]})


class TestProductPricing(ProductAPITestSuite):
	"""The region-aware calculated price through the cart authority."""

	def price_list(self) -> str:
		return boot_strap_test_master_data.resolve_baseline_settings().selling_price_list

	def cart_anchors(self) -> dict:
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		return {
			"guest_customer": frappe.db.get_value(
				"Customer", {"customer_name": settings.guest_customer_name}
			),
			"company": resolve_company(settings),
			"selling_price_list": settings.selling_price_list,
		}

	def test_a_region_id_prices_the_priced_surfaces(self):
		item = self.published_item(item_code="DEV-API-PRICE-1", item_name="Dev API Price One")
		self.fixtures.item_price(item, 199.5, price_list=self.price_list())
		currency = frappe.db.get_value("Price List", self.price_list(), "currency")

		with self.storefront(priced=True):
			listed = self._dispatch("GET", "/ceto/store/products?region_id=reg_test")
			variants = self._dispatch("GET", "/ceto/store/product-variants?region_id=reg_test")
			detail = self._dispatch(
				"GET", f"/ceto/store/products/{product_public_id(item.name)}?region_id=reg_test"
			)

		price = listed.get_json()["products"][0]["variants"][0]["calculated_price"]
		self.assertEqual(price["calculated_amount"], 199.5)
		self.assertEqual(price["original_amount"], 199.5)
		self.assertEqual(price["currency_code"], currency.lower())
		self.assertIs(price["is_calculated_price_price_list"], True)
		self.assertEqual(variants.get_json()["variants"][0]["calculated_price"], price)
		self.assertEqual(detail.get_json()["product"]["variants"][0]["calculated_price"], price)

	def test_no_region_serves_the_projection_unpriced(self):
		item = self.published_item(item_code="DEV-API-PRICE-2", item_name="Dev API Price Two")
		self.fixtures.item_price(item, 199.5, price_list=self.price_list())

		with self.storefront(priced=True):
			listed = self._dispatch("GET", "/ceto/store/products")
			padded = self._dispatch("GET", "/ceto/store/products?region_id=")
			variants = self._dispatch("GET", "/ceto/store/product-variants")

		served = [
			variant
			for response in (listed, padded)
			for product in response.get_json()["products"]
			for variant in product["variants"]
		] + variants.get_json()["variants"]
		for variant in served:
			self.assertIsNone(variant["calculated_price"])

	def test_an_unknown_region_refuses_like_a_cart(self):
		self.published_item(item_code="DEV-API-PRICE-3", item_name="Dev API Price Three")

		with self.set_conf(
			ceto_catalog={"category_roots": [ROOT]},
			ceto_cart={
				"publishable_keys": PUBLISHABLE_KEYS,
				**self.cart_anchors(),
				"regions": {"reg_other": {}},
			},
		):
			response = self._dispatch("GET", "/ceto/store/products?region_id=reg_test")

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")


class TestProductNotFound(ProductAPITestSuite):
	"""Unknown and unpublished ids mask as the Medusa 404, never a 500."""

	def test_unknown_malformed_and_unpublished_product_ids_mask_as_not_found(self):
		hidden = self.fixtures.item(
			item_code="DEV-API-HIDDEN-1", item_name="Dev API Hidden One", item_group=OUTSIDE
		)

		with self.storefront():
			for product_id in (
				"prod_" + "0" * 32,
				"not-a-product",
				"prod_short",
				product_public_id(hidden.name),
			):
				with self.subTest(product_id=product_id):
					response = self._dispatch("GET", f"/ceto/store/products/{product_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")

	def test_unknown_and_unpublished_option_ids_mask_as_not_found(self):
		colour = self.fixtures.item_attribute("Black", "Red")
		hidden = self.fixtures.template_item(
			item_code="DEV-API-OPTHIDDEN", item_group=OUTSIDE, attributes=[{"attribute": colour}]
		)

		with self.storefront():
			for option_id in (
				"opt_" + "0" * 32,
				"not-an-option",
				"optval_" + "0" * 32,
				option_public_id(hidden.name, colour),
			):
				with self.subTest(option_id=option_id):
					response = self._dispatch("GET", f"/ceto/store/product-options/{option_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")
