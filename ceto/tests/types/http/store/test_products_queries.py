"""Pinned product-surface query parameter contracts.

Pins the ``FindParams`` pagination of the three list params (the upstream
validators default ``offset: 0`` with ``limit: 50`` for products and
options and ``limit: 20`` for variants), the Ceto read-model page bounds
and the unknown-parameter strictness of ``@medusajs/types@2.21.1``
(``http/product/store``) — including the strict pricing boundary: exactly
one pricing-context key (``region_id``) is accepted on the priced
surfaces, while ``country_code`` / ``province`` / ``cart_id`` stay refused
everywhere.
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.products import (
	PRODUCT_LIST_MAX_LIMIT,
	PRODUCT_OPTION_LIST_MAX_LIMIT,
	PRODUCT_VARIANT_LIST_MAX_LIMIT,
	StoreProductListParams,
	StoreProductOptionListParams,
	StoreProductOptionParams,
	StoreProductParams,
	StoreProductVariantListParams,
)

#: The upstream search, filter, operator-map, combinator, sort, ``fields``
#: and pricing-context surfaces are refused on every product list.
REJECTED_PRODUCT_LIST_KEYS = (
	{"q": "t-shirt"},
	{"id": "prod_1"},
	{"title": "Dev T-Shirt"},
	{"handle": "dev-t-shirt"},
	{"subtitle": "Soft"},
	{"description": "Soft cotton"},
	{"is_giftcard": "true"},
	{"discountable": "true"},
	{"status": "published"},
	{"thumbnail": "https://assets.example.com/x.png"},
	{"collection_id": "pcol_1"},
	{"type_id": "ptyp_1"},
	{"tag_id": "ptag_1"},
	{"category_id": "pcat_1"},
	{"categories": "apparel"},
	{"external_id": "erp-1"},
	{"sales_channel_id": "sc_1"},
	{"variants": {"sku": "DEV-TSHIRT-RED"}},
	{"created_at": {"gte": "2026-01-01"}},
	{"updated_at": {"gte": "2026-01-01"}},
	{"deleted_at": {"gte": "2026-01-01"}},
	{"order": "-created_at"},
	{"fields": "id,*variants"},
	{"$and": [{"handle": "dev-t-shirt"}]},
	{"$or": [{"id": "prod_1"}]},
	# Pricing context — only region_id is accepted; the rest stay refused.
	{"country_code": "th"},
	{"province": "10"},
	{"cart_id": "cart_1"},
	{"locale": "en-US"},
)

REJECTED_VARIANT_LIST_KEYS = (
	{"q": "red"},
	{"id": "variant_1"},
	{"sku": "DEV-TSHIRT-RED"},
	{"product_id": "prod_1"},
	{"options": {"option_id": "opt_1", "value": "Red"}},
	{"allow_backorder": "true"},
	{"manage_inventory": "true"},
	{"created_at": {"gte": "2026-01-01"}},
	{"sales_channel_id": "sc_1"},
	{"order": "variant_rank"},
	{"fields": "id,sku"},
	{"$and": [{"sku": "DEV-TSHIRT-RED"}]},
	{"$or": [{"id": "variant_1"}]},
	{"country_code": "th"},
	{"province": "10"},
	{"cart_id": "cart_1"},
)

REJECTED_OPTION_LIST_KEYS = (
	{"q": "color"},
	{"id": "opt_1"},
	{"title": "Color"},
	{"is_exclusive": "true"},
	{"created_at": {"gte": "2026-01-01"}},
	{"order": "title"},
	{"fields": "id,title"},
	{"$and": [{"title": "Color"}]},
	{"$or": [{"id": "opt_1"}]},
)


class TestStoreProductListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreProductListParams()
		self.assertEqual((params.offset, params.limit), (0, 50))

	def test_accepts_an_in_bounds_page(self):
		params = StoreProductListParams(offset=50, limit=PRODUCT_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (50, PRODUCT_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreProductListParams(limit=PRODUCT_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreProductListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreProductListParams(offset=-1)

	def test_region_id_is_the_one_accepted_pricing_context(self):
		self.assertIsNone(StoreProductListParams().region_id)
		self.assertEqual(StoreProductListParams(region_id="reg_1").region_id, "reg_1")
		with self.assertRaises(ValidationError):
			StoreProductListParams(region_id=7)

	def test_rejects_the_upstream_search_filter_sort_and_pricing_surfaces(self):
		for query in REJECTED_PRODUCT_LIST_KEYS:
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductListParams(**query)


class TestStoreProductParams(unittest.TestCase):
	def test_an_empty_query_serves_the_unpriced_default(self):
		self.assertEqual(StoreProductParams().model_dump(), {"region_id": None})

	def test_carries_only_the_region_pricing_context(self):
		self.assertEqual(set(StoreProductParams.model_fields), {"region_id"})
		self.assertIsNone(StoreProductParams().region_id)
		self.assertEqual(StoreProductParams(region_id="reg_1").model_dump(), {"region_id": "reg_1"})

	def test_rejects_every_other_parameter_including_the_pricing_context(self):
		for query in (
			{"fields": "id,*variants"},
			{"country_code": "th"},
			{"province": "10"},
			{"cart_id": "cart_1"},
			{"locale": "en-US"},
			{"limit": "5"},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductParams(**query)


class TestStoreProductVariantListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreProductVariantListParams()
		self.assertEqual((params.offset, params.limit), (0, 20))

	def test_accepts_an_in_bounds_page(self):
		params = StoreProductVariantListParams(offset=20, limit=PRODUCT_VARIANT_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (20, PRODUCT_VARIANT_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreProductVariantListParams(limit=PRODUCT_VARIANT_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreProductVariantListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreProductVariantListParams(offset=-1)

	def test_region_id_is_the_one_accepted_pricing_context(self):
		self.assertIsNone(StoreProductVariantListParams().region_id)
		self.assertEqual(StoreProductVariantListParams(region_id="reg_1").region_id, "reg_1")

	def test_rejects_the_upstream_search_filter_sort_and_pricing_surfaces(self):
		for query in REJECTED_VARIANT_LIST_KEYS:
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductVariantListParams(**query)


class TestStoreProductOptionListParams(unittest.TestCase):
	def test_defaults_to_the_pinned_page(self):
		params = StoreProductOptionListParams()
		self.assertEqual((params.offset, params.limit), (0, 50))

	def test_accepts_an_in_bounds_page(self):
		params = StoreProductOptionListParams(offset=50, limit=PRODUCT_OPTION_LIST_MAX_LIMIT)
		self.assertEqual((params.offset, params.limit), (50, PRODUCT_OPTION_LIST_MAX_LIMIT))

	def test_rejects_an_out_of_bounds_or_negative_page(self):
		with self.assertRaises(ValidationError):
			StoreProductOptionListParams(limit=PRODUCT_OPTION_LIST_MAX_LIMIT + 1)
		with self.assertRaises(ValidationError):
			StoreProductOptionListParams(limit=-1)
		with self.assertRaises(ValidationError):
			StoreProductOptionListParams(offset=-1)

	def test_rejects_the_upstream_search_filter_sort_and_combinator_surfaces(self):
		for query in REJECTED_OPTION_LIST_KEYS:
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductOptionListParams(**query)


class TestStoreProductOptionParams(unittest.TestCase):
	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreProductOptionParams().model_dump(), {})

	def test_carries_no_field_at_all(self):
		self.assertEqual(StoreProductOptionParams.model_fields, {})

	def test_rejects_every_parameter(self):
		for query in (
			{"fields": "id,title,*values"},
			{"limit": "5"},
			{"q": "color"},
			{"product_id": "prod_1"},
		):
			with self.subTest(query=query):
				with self.assertRaises(ValidationError):
					StoreProductOptionParams(**query)


if __name__ == "__main__":
	unittest.main()
