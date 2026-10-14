"""Catalog-to-cart round trip: served variant identities price carts exactly.

The golden assortment (:mod:`ceto.tests.golden.catalog`) is the product
fixture: one priced read of the published assortment serves every sellable
unit with its region-aware ``calculated_price``. This suite walks the round
trip the storefront promises — every variant identity the catalog returns
can be added to a guest cart through the same public router boundary, and
the resulting cart line's ERPNext-computed unit price reconciles exactly
with the calculated price the catalog served for that identity: same price
list, same currency, no drift between the two projections.

The identity split is pinned from the negative side too, because the round
trip only proves what it claims when nothing else reaches a cart: the
family head is a served product id but never a served variant identity
(publication keeps templates unsellable), and a derived product id is never
a cart identity — both refuse as ``invalid_data`` like any unpublished id,
so the catalog and cart identity spaces intersect exactly at the served
variant ids.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

# Importing the module registers the dispatch table on the router.
import ceto.api.routes
from ceto.routing import ceto_router
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.golden.catalog import (
	GOLDEN_REGION_ID,
	GOLDEN_SOCK,
	GOLDEN_TEE,
	GOLDEN_TEE_BLACK,
	GOLDEN_TEE_RED,
	PUBLISHABLE_KEY,
	build_golden_assortment,
	golden_storefront,
)
from ceto.tests.utils import CetoTestSuite

SALES_CHANNEL_ID = "sc_test"


class CatalogCartRoundTripSuite(CetoTestSuite):
	"""Every test serves and shops the same deterministic golden assortment."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.assortment = build_golden_assortment(self.fixtures)

	@contextmanager
	def storefront(self) -> Iterator[None]:
		"""Scope the golden storefront plus the scoped key the carts ride.

		The golden cart anchors already resolve ``GOLDEN_REGION_ID`` — the
		configuration carries no ``regions`` overlay, so the value passes
		through to the baseline selling price list — and the key scope
		stamps the same region and channel on every created cart, exactly
		like a configured deployment.
		"""
		conf = golden_storefront()
		conf["ceto_cart"] = {
			**conf["ceto_cart"],
			"default_region_id": GOLDEN_REGION_ID,
			"default_sales_channel_id": SALES_CHANNEL_ID,
			"publishable_keys": {
				PUBLISHABLE_KEY: {"region_id": GOLDEN_REGION_ID, "sales_channel_id": SALES_CHANNEL_ID}
			},
		}
		with self.set_conf(**conf):
			yield

	def _dispatch(self, method: str, path: str, payload: dict | None = None):
		builder = EnvironBuilder(
			path=path,
			method=method,
			data=json.dumps(payload) if payload is not None else None,
			content_type="application/json" if payload is not None else None,
			headers={"x-publishable-api-key": PUBLISHABLE_KEY},
			environ_base={"REMOTE_ADDR": "127.0.0.1"},
		)
		request = Request(builder.get_environ())
		with self.set_request(request):
			return ceto_router.dispatch(request)

	def _priced_served_variants(self) -> dict[str, dict]:
		"""The priced variant identities both catalog read surfaces serve."""
		with self.storefront(), self.set_user("Guest"):
			products = self._dispatch("GET", f"/ceto/store/products?region_id={GOLDEN_REGION_ID}")
			variants = self._dispatch("GET", f"/ceto/store/product-variants?region_id={GOLDEN_REGION_ID}")
		self.assertEqual(products.status_code, 200, products.get_json())
		self.assertEqual(variants.status_code, 200, variants.get_json())
		embedded = {
			variant["id"]: variant["calculated_price"]
			for product in products.get_json()["products"]
			for variant in product["variants"]
		}
		surface = {variant["id"]: variant["calculated_price"] for variant in variants.get_json()["variants"]}
		self.assertEqual(set(embedded), set(surface))
		return embedded

	def _create_cart(self) -> str:
		created = self._dispatch("POST", "/ceto/store/carts?fields=id", {})
		self.assertEqual(created.status_code, 200, created.get_json())
		return created.get_json()["cart"]["id"]


class TestCatalogToCartRoundTrip(CatalogCartRoundTripSuite):
	"""The priced catalog read reconciles with the cart it fills."""

	def test_every_served_variant_adds_at_its_calculated_price(self) -> None:
		served = self._priced_served_variants()
		# The fixture's sellable units are exactly the identities the
		# assortment serves — priced, no orphans, no family head.
		self.assertEqual(set(served), {GOLDEN_TEE_BLACK, GOLDEN_TEE_RED, GOLDEN_SOCK})
		with self.storefront(), self.set_user("Guest"):
			cart_id = self._create_cart()
			for variant_id, price in sorted(served.items()):
				with self.subTest(variant_id=variant_id):
					added = self._dispatch(
						"POST",
						f"/ceto/store/carts/{cart_id}/line-items?fields=id,currency_code,items",
						{"variant_id": variant_id, "quantity": 1},
					)
					self.assertEqual(added.status_code, 200, added.get_json())
					cart = added.get_json()["cart"]
					self.assertEqual(cart["currency_code"], price["currency_code"])
					line = cart["items"][-1]
					self.assertEqual(line["variant_id"], variant_id)
					self.assertEqual(line["quantity"], 1)
					# The reconciliation: the cart line prices exactly what the
					# catalog calculated for the same identity.
					self.assertEqual(line["unit_price"], price["calculated_amount"])
					self.assertEqual(line["original_unit_price"], price["original_amount"])
			filled = self._dispatch("GET", f"/ceto/store/carts/{cart_id}?fields=id,items")
			self.assertEqual(filled.status_code, 200, filled.get_json())
			self.assertEqual(
				[item["variant_id"] for item in filled.get_json()["cart"]["items"]], sorted(served)
			)


class TestCatalogCartIdentitySplit(CatalogCartRoundTripSuite):
	"""No catalog identity outside the served variant ids reaches a cart."""

	def test_the_family_head_is_never_a_cart_identity(self) -> None:
		with self.storefront(), self.set_user("Guest"):
			cart_id = self._create_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": GOLDEN_TEE, "quantity": 1},
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")

	def test_a_served_product_id_is_never_a_cart_identity(self) -> None:
		with self.storefront(), self.set_user("Guest"):
			cart_id = self._create_cart()
			response = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": self.assortment.product_id, "quantity": 1},
			)
		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.get_json()["type"], "invalid_data")
