"""Golden contract pins for the five product/variant/option routes.

The boundary suite pins behaviour query-by-query; this suite pins the
whole served body. Each test dispatches one pinned route over the fully
deterministic golden assortment (`ceto.tests.golden.catalog`) and compares
the complete JSON response — every column, null, derived id, embedded
projection, ordering and envelope echo — against the frozen body in
``ceto.tests.golden.product_responses``. Together they close the gap a
field-by-field suite always leaves: an added, dropped, renamed or
re-typed served column, a re-derived public id, a re-ordered list or a
re-formatted timestamp cannot land without a deliberate golden update.

The reads are the pinned fullest shapes — the three priced surfaces serve
a resolved ``calculated_price`` through the cart price-list authority,
the option surfaces their pricing-free projections — with the strict
publishable-key boundary, the exact Medusa envelopes and the pricing
semantics untouched (their behaviour coverage lives in
``test_products.py``; this suite freezes the bodies, not the rules).
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
from ceto.tests.golden import product_responses
from ceto.tests.golden.catalog import (
	GOLDEN_REGION_ID,
	PUBLISHABLE_KEY,
	build_golden_assortment,
	golden_storefront,
)
from ceto.tests.utils import CetoTestSuite


class ProductGoldenSuite(CetoTestSuite):
	"""Every test serves the same deterministic assortment."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.assortment = build_golden_assortment(CatalogTestData())

	@contextmanager
	def storefront(self) -> Iterator[None]:
		"""Scope the golden storefront: its own root plus the priced anchors."""
		with self.set_conf(**golden_storefront()):
			yield

	def serve(self, path: str) -> dict:
		"""Dispatch one guest GET with the golden publishable key."""
		builder = EnvironBuilder(
			path=path,
			method="GET",
			headers={"x-publishable-api-key": PUBLISHABLE_KEY},
			environ_base={"REMOTE_ADDR": "127.0.0.1"},
		)
		request = Request(builder.get_environ())
		with self.set_request(request):
			response = ceto_router.dispatch(request)
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.content_type, "application/json")
		return json.loads(response.get_data(as_text=True))


class TestProductGoldenBodies(ProductGoldenSuite):
	"""The five served bodies, pinned column for column."""

	def test_the_product_list_serves_the_pinned_body(self) -> None:
		with self.storefront():
			body = self.serve(f"/ceto/store/products?region_id={GOLDEN_REGION_ID}")
		self.assertEqual(body, product_responses.GOLDEN_PRODUCT_LIST_BODY)

	def test_the_product_detail_serves_the_pinned_body(self) -> None:
		with self.storefront():
			body = self.serve(
				f"/ceto/store/products/{self.assortment.product_id}?region_id={GOLDEN_REGION_ID}"
			)
		self.assertEqual(body, product_responses.GOLDEN_PRODUCT_DETAIL_BODY)

	def test_the_variants_surface_serves_the_pinned_body(self) -> None:
		with self.storefront():
			body = self.serve(f"/ceto/store/product-variants?region_id={GOLDEN_REGION_ID}")
		self.assertEqual(body, product_responses.GOLDEN_VARIANT_LIST_BODY)

	def test_the_options_surface_serves_the_pinned_body(self) -> None:
		with self.storefront():
			body = self.serve("/ceto/store/product-options")
		self.assertEqual(body, product_responses.GOLDEN_OPTION_LIST_BODY)

	def test_the_option_detail_serves_the_pinned_body(self) -> None:
		with self.storefront():
			body = self.serve(f"/ceto/store/product-options/{self.assortment.option_id}")
		self.assertEqual(body, product_responses.GOLDEN_OPTION_DETAIL_BODY)
