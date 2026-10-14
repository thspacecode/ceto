"""The published assortment assembled into Store product families.

``assemble`` is the visibility boundary of the products projection: a
product is an eligible template or a standalone published item, every
sellable unit is an exact ``Item`` code, and an ineligible head's variants
are orphans that never serve. The tests pin the family semantics (the
products field-mapping decisions), the published-values-only option
derivation, the head-ordered variant attributes and the deterministic
served order (taxonomy Recorded Decision 6).
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from frappe.utils import get_datetime

from ceto.services.catalog.families import assemble
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite

ROOT = "Families Root"
IN_ROOT = "Families Apparel"
OUTSIDE = "Families Outside"


class TestAssemble(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(IN_ROOT, parent=ROOT)
		self.fixtures.item_group(OUTSIDE)

	@contextmanager
	def publish(self, roots: tuple[str, ...] = (ROOT,)) -> Iterator[None]:
		"""Scope the storefront boundary the assortment is assembled from."""
		with self.set_conf(ceto_catalog={"category_roots": list(roots)}):
			yield

	def published_item(self, **overrides):
		overrides.setdefault("item_group", IN_ROOT)
		return self.fixtures.item(**overrides)

	def test_an_unconfigured_or_unknown_boundary_publishes_nothing(self) -> None:
		self.published_item()

		with self.publish(roots=()):
			assortment = assemble()
		self.assertEqual(assortment.products, ())
		self.assertEqual(assortment.variants, ())

		with self.publish(roots=("Families Missing Root",)):
			assortment = assemble()
		self.assertEqual(assortment.products, ())
		self.assertEqual(assortment.variants, ())

	def test_a_template_and_its_published_variants_serve_one_family(self) -> None:
		attribute = self.fixtures.item_attribute("Black", "Red")
		template = self.fixtures.template_item(item_group=IN_ROOT, attributes=[{"attribute": attribute}])
		first = self.fixtures.variant_item(template)
		second = self.fixtures.variant_item(template, attribute_value="Red")

		with self.publish():
			assortment = assemble()

		self.assertEqual(len(assortment.products), 1)
		served = assortment.products[0]
		self.assertEqual(served.item.item_code, template.name)
		self.assertEqual(
			[variant.item.item_code for variant in served.variants], sorted([first.name, second.name])
		)
		self.assertEqual([variant.product.item_code for variant in served.variants], [template.name] * 2)
		self.assertEqual(
			[variant.item.item_code for variant in assortment.variants], sorted([first.name, second.name])
		)
		# The template head is never a sellable unit itself.
		self.assertNotIn(template.name, [variant.item.item_code for variant in assortment.variants])

	def test_a_standalone_item_is_its_own_product_and_only_variant(self) -> None:
		standalone = self.published_item()

		with self.publish():
			assortment = assemble()

		self.assertEqual(len(assortment.products), 1)
		served = assortment.products[0]
		self.assertEqual(served.item.item_code, standalone.name)
		self.assertEqual(len(served.variants), 1)
		variant = served.variants[0]
		self.assertEqual(variant.item.item_code, standalone.name)
		self.assertEqual(variant.product.item_code, standalone.name)
		self.assertEqual(variant.attributes, ())
		# No family, no options — the shape an option-less product carries.
		self.assertEqual(served.options, ())
		self.assertEqual([variant.item.item_code for variant in assortment.variants], [standalone.name])

	def test_an_orphan_variant_of_an_ineligible_head_never_serves(self) -> None:
		# A disabled head and a head outside the configured roots both leave
		# their variants orphans: not a product, not a variant.
		disabled_head = self.fixtures.template_item(item_group=IN_ROOT, disabled=1)
		outside_head = self.fixtures.template_item(item_group=OUTSIDE)
		orphan_one = self.fixtures.variant_item(disabled_head)
		orphan_two = self.fixtures.variant_item(outside_head)

		with self.publish():
			assortment = assemble()

		self.assertEqual(assortment.products, ())
		self.assertEqual(assortment.variants, ())
		for orphan in (orphan_one, orphan_two):
			self.assertNotIn(orphan.name, [variant.item.item_code for variant in assortment.variants])

	def test_a_family_with_zero_published_variants_still_serves(self) -> None:
		template = self.fixtures.template_item(item_group=IN_ROOT)

		with self.publish():
			assortment = assemble()

		self.assertEqual(len(assortment.products), 1)
		served = assortment.products[0]
		self.assertEqual(served.item.item_code, template.name)
		self.assertEqual(served.variants, ())
		# Eligibility is the assortment boundary, not a sales record: the
		# head projects its (empty) options and never joins the surface.
		self.assertEqual(len(served.options), 1)
		self.assertEqual(served.options[0].values, ())
		self.assertEqual(assortment.variants, ())

	def test_the_base_publication_rules_scope_every_member(self) -> None:
		disabled = self.published_item(disabled=1)
		non_sales = self.published_item(is_sales_item=0)
		outside = self.fixtures.item(item_group=OUTSIDE)
		kept = self.published_item()

		with self.publish():
			assortment = assemble()

		served_codes = [served.item.item_code for served in assortment.products]
		self.assertEqual(served_codes, [kept.name])
		for excluded in (disabled, non_sales, outside):
			self.assertNotIn(excluded.name, served_codes)

	def test_options_project_only_the_values_published_variants_carry(self) -> None:
		attribute = self.fixtures.item_attribute("Black", "Red")
		template = self.fixtures.template_item(item_group=IN_ROOT, attributes=[{"attribute": attribute}])
		self.fixtures.variant_item(template)

		with self.publish():
			assortment = assemble()

		options = assortment.products[0].options
		self.assertEqual([(option.attribute, option.values) for option in options], [(attribute, ("Black",))])

	def test_variant_attributes_keep_the_family_head_option_order(self) -> None:
		colour = self.fixtures.item_attribute("Black")
		size = self.fixtures.item_attribute("Small", "Large")
		template = self.fixtures.template_item(
			item_group=IN_ROOT, attributes=[{"attribute": colour}, {"attribute": size}]
		)
		variant = self.fixtures.variant_item(
			template,
			attributes=[
				{"attribute": size, "attribute_value": "Large"},
				{"attribute": colour, "attribute_value": "Black"},
			],
		)

		with self.publish():
			assortment = assemble()

		served = assortment.products[0]
		self.assertEqual([option.attribute for option in served.options], [colour, size])
		self.assertEqual(
			served.variants[0].attributes,
			((colour, "Black"), (size, "Large")),
		)
		self.assertEqual(served.variants[0].item.item_code, variant.name)

	def test_the_served_and_surface_orders_are_deterministic(self) -> None:
		alpha = self.published_item(item_name="Dev Alpha", item_code="DEV-FAM-ALPHA")
		zulu = self.published_item(item_name="Dev Alpha", item_code="DEV-FAM-ZULU")
		mike = self.published_item(item_name="Dev Mike", item_code="DEV-FAM-MIKE")
		attribute = self.fixtures.item_attribute("Black", "Red")
		template = self.fixtures.template_item(
			item_group=IN_ROOT,
			item_name="Dev Alpha",
			item_code="DEV-FAM-TMPL",
			attributes=[{"attribute": attribute}],
		)
		late_variant = self.fixtures.variant_item(template, attribute_value="Red", item_code="DEV-FAM-VZZ")
		early_variant = self.fixtures.variant_item(template, item_code="DEV-FAM-VAA")

		with self.publish():
			assortment = assemble()

		# Products order by item name then item code; the variants surface
		# orders by item code; option values ascend.
		self.assertEqual(
			[served.item.item_code for served in assortment.products],
			[alpha.name, template.name, zulu.name, mike.name],
		)
		self.assertEqual(
			[variant.item.item_code for variant in assortment.variants],
			sorted([early_variant.name, late_variant.name, alpha.name, zulu.name, mike.name]),
		)
		# Option values ascend across the published variants of the family.
		self.assertEqual(assortment.products[1].options[0].values, ("Black", "Red"))

	def test_a_projection_carries_the_real_item_row(self) -> None:
		item = self.published_item(
			item_name="Dev Projection",
			description="Dev description",
			image="/files/dev.png",
			country_of_origin="Thailand",
		)

		with self.publish():
			projected = assemble().products[0].item

		self.assertEqual(projected.item_code, item.name)
		self.assertEqual(projected.title, "Dev Projection")
		self.assertEqual(projected.description, "Dev description")
		self.assertEqual(projected.image, "/files/dev.png")
		self.assertEqual(projected.origin_country, "Thailand")
		self.assertEqual(projected.stock_uom, item.stock_uom)
		self.assertEqual(projected.created_at, get_datetime(item.creation))
		self.assertEqual(projected.updated_at, get_datetime(item.modified))

		self.published_item(item_name="Dev Blank Projection")
		with self.publish():
			blank_projection = assemble().products[0].item
		self.assertIsNone(blank_projection.description)
		self.assertIsNone(blank_projection.image)
		self.assertIsNone(blank_projection.origin_country)
		self.assertIsNotNone(blank_projection.created_at)
