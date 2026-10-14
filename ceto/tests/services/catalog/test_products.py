"""The served product projections over the published assortment.

``ProductCatalog`` is the serialization half of the products foundation:
the assembled assortment projects onto the pinned ``StoreProduct`` /
``StoreProductVariant`` contracts with every enrichment batched — the
merchandising links, the embedded collection/type/category/tag
projections, the barcodes and the region-aware prices each load in one
bulk query for the whole served set. The tests pin the served shapes and
the derived identities (products field-mapping decision 7), the page
echo over the whole assortment, the masked unknown id, the canonical
variants surface and the fixed query budget a page costs no matter how
large the assortment grows.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

import frappe
from frappe.utils import get_datetime

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.catalog.product_categories import category_public_id
from ceto.services.catalog.product_tags import tag_public_id
from ceto.services.catalog.products import (
	ProductCatalog,
	image_public_id,
	option_public_id,
	option_value_public_id,
	product_public_id,
)
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data
from ceto.types.http.store.products import PRODUCT_LIST_MAX_LIMIT

ROOT = "Products Root"
IN_ROOT = "Products Apparel"
OUTSIDE = "Products Outside"


class ProductsTestSuite(CetoTestSuite):
	"""Shared anchors: the storefront roots and, when priced, the cart ones."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(IN_ROOT, parent=ROOT)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self, roots: tuple[str, ...] = (ROOT,)) -> Iterator[None]:
		"""Scope the storefront boundary the projections serve."""
		with self.set_conf(ceto_catalog={"category_roots": list(roots)}):
			yield

	@contextmanager
	def priced(self) -> Iterator[None]:
		"""Scope a configured deployment: storefront roots plus cart anchors."""
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		with self.set_conf(
			ceto_catalog={"category_roots": [ROOT]},
			ceto_cart={
				"guest_customer": frappe.db.get_value(
					"Customer", {"customer_name": settings.guest_customer_name}
				),
				"company": resolve_company(settings),
				"selling_price_list": settings.selling_price_list,
			},
		):
			yield

	def published_item(self, **overrides):
		overrides.setdefault("item_group", IN_ROOT)
		return self.fixtures.item(**overrides)


class TestProductSurfaces(ProductsTestSuite):
	def test_an_empty_assortment_serves_an_empty_page(self) -> None:
		with self.publish(roots=()):
			page = ProductCatalog().list()
			variants = ProductCatalog().variant_page()
		self.assertEqual((page.products, page.count, page.offset), ([], 0, 0))
		self.assertEqual((variants.variants, variants.count), ([], 0))

		self.published_item()
		with self.publish(roots=("Products Missing Root",)):
			self.assertEqual(ProductCatalog().list().count, 0)

	def test_a_standalone_item_serves_the_pinned_projection(self) -> None:
		item = self.published_item(
			item_code="DEV-PROJ-SOCK",
			item_name="Dev Project Sock",
			description="Dev description",
			image="/files/dev-sock.png",
		)

		with self.publish():
			response = ProductCatalog().get(product_public_id(item.name))

		product = response.product
		self.assertEqual(product.id, product_public_id(item.name))
		self.assertEqual(product.title, "Dev Project Sock")
		self.assertEqual(product.handle, "dev-project-sock")
		self.assertEqual(product.description, "Dev description")
		self.assertEqual(product.thumbnail, "/files/dev-sock.png")
		self.assertEqual(
			[(image.id, image.url) for image in product.images],
			[(image_public_id(item.name), "/files/dev-sock.png")],
		)
		self.assertEqual([category.id for category in product.categories], [category_public_id(IN_ROOT)])
		self.assertEqual((product.collection_id, product.collection), (None, None))
		self.assertEqual((product.type_id, product.type), (None, None))
		self.assertEqual(product.created_at, get_datetime(item.creation))
		self.assertEqual(product.updated_at, get_datetime(item.modified))
		self.assertIsNone(product.deleted_at)
		# The standalone item is its own sellable unit, option-less and
		# unpriced without a region.
		self.assertEqual(len(product.variants), 1)
		variant = product.variants[0]
		self.assertEqual(variant.id, item.name)
		self.assertEqual(variant.sku, item.name)
		self.assertEqual(variant.title, "Dev Project Sock")
		self.assertEqual(variant.product_id, product.id)
		self.assertEqual(variant.options, [])
		self.assertIsNone(variant.calculated_price)

	def test_a_family_serves_its_options_with_the_variant_bindings(self) -> None:
		attribute = self.fixtures.item_attribute("Black", "Red")
		template = self.fixtures.template_item(
			item_code="DEV-FAM-HEAD",
			item_name="Dev Fam Head",
			item_group=IN_ROOT,
			attributes=[{"attribute": attribute}],
		)
		self.fixtures.variant_item(template, item_code="DEV-FAM-BLACK")
		self.fixtures.variant_item(template, attribute_value="Red", item_code="DEV-FAM-RED")

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		self.assertEqual(page.count, 1)
		product = page.products[0]
		self.assertEqual(product.id, product_public_id(template.name))
		self.assertEqual([option.title for option in product.options], [attribute])
		option = product.options[0]
		self.assertEqual(option.id, option_public_id(template.name, attribute))
		self.assertEqual(
			[(value.id, value.value) for value in option.values],
			[
				(option_value_public_id(template.name, attribute, "Black"), "Black"),
				(option_value_public_id(template.name, attribute, "Red"), "Red"),
			],
		)
		# Variants serve in item-code order, the template head itself never
		# becomes one, and each binds back to its owning product.
		self.assertEqual([variant.sku for variant in product.variants], ["DEV-FAM-BLACK", "DEV-FAM-RED"])
		by_sku = {variant.sku: variant for variant in product.variants}
		self.assertEqual(by_sku["DEV-FAM-RED"].id, "DEV-FAM-RED")
		self.assertEqual(by_sku["DEV-FAM-RED"].product_id, product.id)
		self.assertEqual(by_sku["DEV-FAM-RED"].options[0].option_id, option.id)
		self.assertEqual(
			by_sku["DEV-FAM-RED"].options[0].id, option_value_public_id(template.name, attribute, "Red")
		)

	def test_a_family_without_variants_serves_an_empty_variants_list(self) -> None:
		self.fixtures.template_item(item_code="DEV-BARE-HEAD", item_name="Dev Bare Head", item_group=IN_ROOT)

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		product = page.products[0]
		self.assertEqual(product.variants, [])
		self.assertEqual(len(product.options), 1)
		self.assertEqual(product.options[0].values, [])

	def test_the_list_echoes_the_page_over_the_whole_assortment(self) -> None:
		for suffix in "ABC":
			self.published_item(item_code=f"DEV-PAGE-{suffix}", item_name=f"Dev Page {suffix}")

		with self.publish():
			whole = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)
			page = ProductCatalog().list(limit=2, offset=1)
			beyond = ProductCatalog().list(offset=10)
			clamped = ProductCatalog().list(limit=10_000)

		self.assertEqual(whole.count, 3)
		self.assertEqual(
			[product.handle for product in whole.products], ["dev-page-a", "dev-page-b", "dev-page-c"]
		)
		self.assertEqual([product.handle for product in page.products], ["dev-page-b", "dev-page-c"])
		self.assertEqual((page.count, page.offset, page.limit), (3, 1, 2))
		self.assertEqual((beyond.products, beyond.count), ([], 3))
		self.assertEqual(clamped.limit, PRODUCT_LIST_MAX_LIMIT)

	def test_an_unknown_or_unpublished_id_masks_as_a_404(self) -> None:
		hidden = self.fixtures.item(item_code="DEV-HIDDEN-1", item_name="Dev Hidden One", item_group=OUTSIDE)

		with self.publish():
			for product_id in ("", "prod_does_not_exist", product_public_id(hidden.name)):
				with self.subTest(product_id=product_id):
					with self.assertRaises(RouteNotFoundError):
						ProductCatalog().get(product_id)

	def test_a_shared_title_slug_disambiguates_every_member(self) -> None:
		first = self.published_item(item_code="DEV-CLASH-A", item_name="Dev Clash Tee")
		second = self.published_item(item_code="DEV-CLASH-B", item_name="Dev Clash Tee")
		solo = self.published_item(item_code="DEV-CLASH-C", item_name="Dev Solo Tee")

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)
			again = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		by_id = {product.id: product for product in page.products}
		clash_one = by_id[product_public_id(first.name)].handle
		clash_two = by_id[product_public_id(second.name)].handle
		self.assertNotEqual(clash_one, clash_two)
		# The suffix is the member's own product-id digest, so the same
		# assortment always resolves to the same handles.
		for handle, item in ((clash_one, first), (clash_two, second)):
			self.assertEqual(
				handle, f"dev-clash-tee-{product_public_id(item.name).removeprefix('prod_')[:8]}"
			)
		self.assertEqual(by_id[product_public_id(solo.name)].handle, "dev-solo-tee")
		self.assertEqual(
			{product.id: product.handle for product in again.products},
			{product.id: product.handle for product in page.products},
		)

	def test_a_title_that_slugs_to_nothing_falls_back_to_the_item_code(self) -> None:
		self.published_item(item_code="DEV-SYM-9", item_name="***")

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		self.assertEqual(page.products[0].handle, "dev-sym-9")

	def test_the_merchandising_link_serves_the_collection_and_type_projections(self) -> None:
		linked = self.published_item(item_code="DEV-MERCH-A", item_name="Dev Merch A")
		self.published_item(item_code="DEV-MERCH-B", item_name="Dev Merch B")
		collection = self.fixtures.collection(title="Dev Merch Collection")
		product_type = self.fixtures.product_type(value="Dev Merch Type")
		self.fixtures.merchandising(linked, collection=collection, product_type=product_type)

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		by_title = {product.title: product for product in page.products}
		served = by_title["Dev Merch A"]
		self.assertEqual(served.collection_id, collection.collection_id)
		self.assertEqual(
			(served.collection.id, served.collection.title),
			(collection.collection_id, "Dev Merch Collection"),
		)
		self.assertEqual(served.type_id, product_type.type_id)
		self.assertEqual((served.type.id, served.type.value), (product_type.type_id, "Dev Merch Type"))
		unlinked = by_title["Dev Merch B"]
		self.assertEqual((unlinked.collection_id, unlinked.collection), (None, None))
		self.assertEqual((unlinked.type_id, unlinked.type), (None, None))

	def test_the_barcode_rows_serve_the_typed_columns(self) -> None:
		item = self.published_item(item_code="DEV-BARCODE-1", item_name="Dev Barcode One")
		self.fixtures.barcode(item, "DEV-BARCODE-FIRST")
		self.fixtures.barcode(item, "4006381333931", barcode_type="EAN-13")
		self.fixtures.barcode(item, "012345678905", barcode_type="UPC-A")

		with self.publish():
			page = ProductCatalog().variant_page(limit=PRODUCT_LIST_MAX_LIMIT)

		variant = next(candidate for candidate in page.variants if candidate.sku == item.name)
		self.assertEqual(variant.barcode, "DEV-BARCODE-FIRST")
		self.assertEqual(variant.ean, "4006381333931")
		self.assertEqual(variant.upc, "012345678905")

	def test_the_item_tags_embed_their_live_projections(self) -> None:
		tagged = self.published_item(item_code="DEV-TAGGED-1", item_name="Dev Tagged One")
		other = self.published_item(item_code="DEV-TAGGED-2", item_name="Dev Tagged Two")
		value = self.fixtures.item_tag(tagged, "Dev Projection Tag")
		self.fixtures.item_tag(other, "Dev Other Tag")

		with self.publish():
			page = ProductCatalog().list(limit=PRODUCT_LIST_MAX_LIMIT)

		by_title = {product.title: product for product in page.products}
		self.assertEqual(
			[(tag.id, tag.value) for tag in by_title["Dev Tagged One"].tags],
			[(tag_public_id(value), value)],
		)
		self.assertEqual([tag.value for tag in by_title["Dev Tagged Two"].tags], ["Dev Other Tag"])

	def test_the_variants_surface_serves_every_sellable_unit_in_item_code_order(self) -> None:
		standalone = self.published_item(item_code="DEV-SURF-SOLO", item_name="Dev Surf Solo")
		attribute = self.fixtures.item_attribute("Black", "Red")
		template = self.fixtures.template_item(
			item_code="DEV-SURF-HEAD",
			item_name="Dev Surf Head",
			item_group=IN_ROOT,
			attributes=[{"attribute": attribute}],
		)
		self.fixtures.variant_item(template, item_code="DEV-SURF-BLACK")
		self.fixtures.variant_item(template, attribute_value="Red", item_code="DEV-SURF-RED")
		orphan_head = self.fixtures.template_item(item_code="DEV-SURF-ORPH", item_group=OUTSIDE)
		orphan = self.fixtures.variant_item(orphan_head)

		with self.publish():
			page = ProductCatalog().variant_page(limit=PRODUCT_LIST_MAX_LIMIT)

		self.assertEqual(
			[variant.sku for variant in page.variants],
			["DEV-SURF-BLACK", "DEV-SURF-RED", "DEV-SURF-SOLO"],
		)
		by_sku = {variant.sku: variant for variant in page.variants}
		self.assertEqual(by_sku["DEV-SURF-RED"].product_id, product_public_id(template.name))
		self.assertEqual(by_sku["DEV-SURF-SOLO"].product_id, product_public_id(standalone.name))
		for unsellable in (template.name, orphan.name, orphan_head.name):
			self.assertNotIn(unsellable, by_sku)


class TestQueryBudget(ProductsTestSuite):
	"""A page is a fixed set of bulk reads, never a per-item walk."""

	@contextmanager
	def counted_queries(self) -> Iterator[mock.Mock]:
		"""Spy on ``frappe.db.sql`` for the block: the query builder and
		``frappe.get_all`` both run through it."""
		with mock.patch.object(frappe.db, "sql", wraps=frappe.db.sql) as spy:
			yield spy

	def catalogued_family(self, *, head_code: str, member_code: str, barcode: str) -> None:
		"""One family carrying every enrichment: link, tag and barcode."""
		attribute = self.fixtures.item_attribute("Black", "Red")
		head = self.fixtures.template_item(
			item_code=head_code, item_group=IN_ROOT, attributes=[{"attribute": attribute}]
		)
		member = self.fixtures.variant_item(head, item_code=member_code)
		self.fixtures.merchandising(
			head, collection=self.fixtures.collection(), product_type=self.fixtures.product_type()
		)
		self.fixtures.item_tag(head)
		self.fixtures.barcode(member, barcode, barcode_type="EAN-13")

	def test_a_page_costs_the_same_bulk_reads_at_any_assortment_size(self) -> None:
		with self.priced():
			self.catalogued_family(
				head_code="DEV-BUDGET-AH", member_code="DEV-BUDGET-AM", barcode="4006381333931"
			)
			ProductCatalog().list()
			ProductCatalog().list(region_id="reg_test")
			ProductCatalog().variant_page()
			with self.counted_queries() as small:
				ProductCatalog().list()
			with self.counted_queries() as priced_small:
				ProductCatalog().list(region_id="reg_test")

			self.published_item(item_code="DEV-BUDGET-B", item_name="Dev Budget B")
			self.published_item(item_code="DEV-BUDGET-C", item_name="Dev Budget C")
			self.catalogued_family(
				head_code="DEV-BUDGET-DH", member_code="DEV-BUDGET-DM", barcode="5901234123457"
			)
			ProductCatalog().list()
			with self.counted_queries() as large:
				ProductCatalog().list()
			with self.counted_queries() as priced_large:
				ProductCatalog().list(region_id="reg_test")
			with self.counted_queries() as variants:
				ProductCatalog().variant_page()

		self.assertGreater(small.call_count, 0)
		self.assertEqual(large.call_count, small.call_count)
		self.assertEqual(priced_large.call_count, priced_small.call_count)
		self.assertEqual(variants.call_count, small.call_count)

	def test_pricing_a_page_adds_the_two_region_reads(self) -> None:
		first = self.published_item(item_code="DEV-BUDGET-E", item_name="Dev Budget E")
		second = self.published_item(item_code="DEV-BUDGET-F", item_name="Dev Budget F")
		price_list = boot_strap_test_master_data.resolve_baseline_settings().selling_price_list
		self.fixtures.item_price(first, 10.0, price_list=price_list)
		self.fixtures.item_price(second, 20.0, price_list=price_list)

		with self.priced():
			ProductCatalog().list()
			ProductCatalog().list(region_id="reg_test")
			with self.counted_queries() as unpriced:
				ProductCatalog().list()
			with self.counted_queries() as priced:
				ProductCatalog().list(region_id="reg_test")

		# Two reads, whatever the variant count: the region's price-list
		# currency, then the page's one bulk Item Price selection.
		self.assertGreater(unpriced.call_count, 0)
		self.assertEqual(priced.call_count, unpriced.call_count + 2)
