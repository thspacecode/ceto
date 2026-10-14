"""Pinned product-surface entity and envelope contracts."""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.collections import StoreCollection
from ceto.types.http.store.product_categories import StoreProductCategory
from ceto.types.http.store.product_tags import StoreProductTag
from ceto.types.http.store.product_types import StoreProductType
from ceto.types.http.store.products import (
	StoreProduct,
	StoreProductImage,
	StoreProductListResponse,
	StoreProductOption,
	StoreProductOptionListResponse,
	StoreProductOptionResponse,
	StoreProductOptionValue,
	StoreProductResponse,
	StoreProductVariant,
	StoreProductVariantListResponse,
)

TIMESTAMP = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)


def product(**overrides):
	kwargs = {
		"id": "prod_1",
		"title": "Dev T-Shirt",
		"handle": "dev-t-shirt",
	}
	kwargs.update(overrides)
	return StoreProduct(**kwargs)


def variant(**overrides):
	kwargs = {
		"id": "DEV-TSHIRT-RED",
		"product_id": "prod_1",
	}
	kwargs.update(overrides)
	return StoreProductVariant(**kwargs)


def option(**overrides):
	kwargs = {
		"id": "opt_1",
		"title": "Color",
	}
	kwargs.update(overrides)
	return StoreProductOption(**kwargs)


def option_value(**overrides):
	kwargs = {
		"id": "optval_1",
		"value": "Red",
	}
	kwargs.update(overrides)
	return StoreProductOptionValue(**kwargs)


def image(**overrides):
	kwargs = {
		"id": "img_1",
		"url": "https://assets.example.com/dev-t-shirt.png",
	}
	kwargs.update(overrides)
	return StoreProductImage(**kwargs)


class TestStoreProductEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = product()
		self.assertEqual((entry.id, entry.title, entry.handle), ("prod_1", "Dev T-Shirt", "dev-t-shirt"))
		# The pinned required relation columns carry the empty projections.
		for relation in ("categories", "tags", "variants", "options", "images"):
			self.assertEqual(getattr(entry, relation), [])

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		for column in ("id", "title", "handle"):
			kwargs = {key: value for key, value in product().model_dump().items() if key != column}
			with self.subTest(column=column):
				with self.assertRaises(ValidationError):
					StoreProduct(**kwargs)

	def test_unmapped_columns_stay_optional_and_default_to_none(self):
		# Ceto never fabricates commerce flags, soft-delete tombstones or
		# links the item-slice decisions have not landed yet (decisions 4).
		entry = product()
		self.assertIsNone(entry.subtitle)
		self.assertIsNone(entry.description)
		self.assertIsNone(entry.is_giftcard)
		self.assertIsNone(entry.discountable)
		self.assertIsNone(entry.status)
		self.assertIsNone(entry.thumbnail)
		self.assertIsNone(entry.collection_id)
		self.assertIsNone(entry.collection)
		self.assertIsNone(entry.type_id)
		self.assertIsNone(entry.type)
		self.assertIsNone(entry.external_id)
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.created_at)
		self.assertIsNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)
		self.assertEqual(product(created_at=TIMESTAMP).created_at, TIMESTAMP)

	def test_the_taxonomy_relations_reuse_the_pinned_entities(self):
		# Decision 3: category ids are the existing derived category ids.
		category = StoreProductCategory(id="pcat_" + "0" * 32, name="Dev T-Shirts", handle="dev-t-shirts")
		entry = product(
			collection=StoreCollection(id="pcol_1", title="Dev Summer", handle="dev-summer"),
			type=StoreProductType(id="ptyp_1", value="Shirt"),
			categories=[category],
			tags=[StoreProductTag(id="ptag_1", value="Dev New Arrival")],
		)
		self.assertEqual(entry.collection.handle, "dev-summer")
		self.assertEqual(entry.type.value, "Shirt")
		self.assertEqual(entry.categories[0].id, "pcat_" + "0" * 32)
		self.assertEqual(entry.tags[0].value, "Dev New Arrival")
		self.assertIsInstance(entry.type, StoreProductType)

	def test_the_empty_relations_are_not_shared_between_instances(self):
		first, second = product(), product()
		first.variants.append(variant())
		self.assertEqual(len(first.variants), 1)
		self.assertEqual(second.variants, [])


class TestStoreProductVariantEntity(unittest.TestCase):
	def test_the_id_is_the_exact_item_code(self):
		# Decision 2: variant ids stay the exact ERPNext Item codes.
		entry = variant()
		self.assertEqual(entry.id, "DEV-TSHIRT-RED")

	def test_the_id_is_required_and_every_commerce_flag_stays_optional(self):
		with self.assertRaises(ValidationError):
			StoreProductVariant()
		entry = variant()
		self.assertIsNone(entry.title)
		self.assertIsNone(entry.sku)
		self.assertIsNone(entry.barcode)
		self.assertIsNone(entry.ean)
		self.assertIsNone(entry.upc)
		self.assertIsNone(entry.thumbnail)
		self.assertIsNone(entry.allow_backorder)
		self.assertIsNone(entry.manage_inventory)
		self.assertIsNone(entry.variant_rank)
		self.assertIsNone(entry.hs_code)
		self.assertIsNone(entry.origin_country)
		self.assertIsNone(entry.material)
		self.assertIsNone(entry.weight)
		self.assertIsNone(entry.created_at)

	def test_the_pricing_and_inventory_columns_are_dropped_entirely(self):
		# Pricing and inventory are behavior-slice decisions; Ceto does not
		# stub contracts that do not exist yet.
		self.assertFalse(hasattr(variant(), "calculated_price"))
		self.assertFalse(hasattr(variant(), "inventory_quantity"))

	def test_the_option_values_carry_the_pinned_recursive_shape(self):
		value = option_value()
		entry = variant(options=[value])
		self.assertEqual(entry.options[0].value, "Red")
		# A value may name its option without embedding it.
		self.assertIsNone(value.option)
		self.assertIsNone(value.option_id)


class TestStoreProductOptionEntity(unittest.TestCase):
	def test_constructs_with_the_pinned_required_pair(self):
		entry = option()
		self.assertEqual((entry.id, entry.title), ("opt_1", "Color"))
		self.assertIsNone(entry.is_exclusive)
		self.assertIsNone(entry.product)
		self.assertEqual(entry.values, [])
		self.assertIsNone(entry.metadata)
		self.assertIsNone(entry.created_at)

	def test_title_is_required(self):
		with self.assertRaises(ValidationError):
			StoreProductOption(id="opt_1")

	def test_the_values_round_trip_through_the_recursive_model(self):
		value = option_value(option=option(values=[]))
		entry = option(values=[value])
		self.assertEqual(entry.values[0].option.title, "Color")


class TestStoreProductImageEntity(unittest.TestCase):
	def test_the_url_is_required_and_the_rank_stays_optional(self):
		entry = image()
		self.assertEqual(entry.url, "https://assets.example.com/dev-t-shirt.png")
		# No ERPNext ranking source exists yet; the rank stays None (gap).
		self.assertIsNone(entry.rank)
		with self.assertRaises(ValidationError):
			StoreProductImage(id="img_1")


class TestProductEnvelopes(unittest.TestCase):
	def test_detail_responses_wrap_their_entities(self):
		self.assertEqual(StoreProductResponse(product=product()).product.handle, "dev-t-shirt")
		self.assertEqual(StoreProductOptionResponse(product_option=option()).product_option.title, "Color")
		with self.assertRaises(ValidationError):
			StoreProductResponse()
		with self.assertRaises(ValidationError):
			StoreProductOptionResponse()

	def test_list_responses_pin_the_paginated_envelopes(self):
		product_page = StoreProductListResponse(products=[product()], count=1, offset=0, limit=50)
		self.assertEqual(product_page.products[0].id, "prod_1")
		self.assertEqual((product_page.count, product_page.offset, product_page.limit), (1, 0, 50))
		variant_page = StoreProductVariantListResponse(variants=[variant()], count=1, offset=0, limit=20)
		self.assertEqual(variant_page.variants[0].id, "DEV-TSHIRT-RED")
		option_page = StoreProductOptionListResponse(product_options=[option()], count=1, offset=0, limit=50)
		self.assertEqual(option_page.product_options[0].id, "opt_1")

	def test_there_is_no_variants_detail_envelope(self):
		# The canonical variants surface is the list route alone.
		self.assertFalse(hasattr(StoreProductVariantListResponse, "variant"))

	def test_the_list_envelopes_carry_nothing_beyond_the_pinned_columns(self):
		# The pinned PaginatedResponse envelope is exactly these four columns.
		self.assertEqual(set(StoreProductListResponse.model_fields), {"products", "count", "offset", "limit"})
		self.assertEqual(
			set(StoreProductVariantListResponse.model_fields), {"variants", "count", "offset", "limit"}
		)
		self.assertEqual(
			set(StoreProductOptionListResponse.model_fields), {"product_options", "count", "offset", "limit"}
		)
