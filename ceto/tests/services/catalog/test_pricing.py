"""Region-aware product pricing over the cart price-list authority.

Products price exactly like carts: a presented ``region_id`` resolves
through :class:`~ceto.services.carts.configuration.CartConfiguration`, so
the served rate is always a rate on the region's selling Price List in
that list's own currency. The tests pin the anonymous ``Item Price`` read —
party/batch-scoped rows never serve, the validity window and the UOM rule
follow the cart path, the newest window leads with the UOM breaking ties —
and the surfaced ``calculated_price``: priced when a region resolves, absent
when none does, never a fabricated zero.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import frappe
from frappe.utils import add_days, get_datetime, today

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing.exceptions import InvalidDataError
from ceto.services.catalog.pricing import PricingAuthority, calculate_prices, resolve_pricing_authority
from ceto.services.catalog.products import ProductCatalog, product_public_id
from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data

ROOT = "Pricing Root"
IN_ROOT = "Pricing Apparel"


class PricingTestSuite(CetoTestSuite):
	"""Shared anchors: the bootstrap commerce masters and a storefront root."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.fixtures.item_group(ROOT, is_group=True)
		self.fixtures.item_group(IN_ROOT, parent=ROOT)
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.price_list = settings.selling_price_list
		self.currency = frappe.db.get_value("Price List", self.price_list, "currency")
		self.guest = frappe.db.get_value("Customer", {"customer_name": settings.guest_customer_name})
		self.cart_conf = {
			"guest_customer": self.guest,
			"company": resolve_company(settings),
			"selling_price_list": self.price_list,
		}

	@contextmanager
	def priced(self, roots: tuple[str, ...] = (ROOT,)) -> Iterator[None]:
		"""Scope a configured deployment: storefront roots plus cart anchors."""
		with self.set_conf(ceto_catalog={"category_roots": list(roots)}, ceto_cart=self.cart_conf):
			yield

	def published_item(self, **overrides):
		overrides.setdefault("item_group", IN_ROOT)
		return self.fixtures.item(**overrides)

	def rate(self, item, amount, **overrides):
		return self.fixtures.item_price(item, amount, price_list=self.price_list, **overrides)


class TestResolvePricingAuthority(PricingTestSuite):
	def test_no_region_is_no_pricing_context(self) -> None:
		for region_id in (None, "", "   "):
			with self.subTest(region_id=region_id):
				self.assertIsNone(resolve_pricing_authority(region_id))

	def test_a_region_resolves_through_the_cart_configuration(self) -> None:
		with self.priced():
			authority = resolve_pricing_authority("reg_test")

		self.assertEqual(
			authority,
			PricingAuthority(
				region_id="reg_test", selling_price_list=self.price_list, currency=self.currency
			),
		)

	def test_a_region_id_resolves_without_its_padding(self) -> None:
		with self.priced():
			authority = resolve_pricing_authority("  reg_test\t")
		self.assertEqual(authority.region_id, "reg_test")

	def test_an_unknown_region_is_refused_like_a_cart(self) -> None:
		with self.set_conf(ceto_cart={**self.cart_conf, "regions": {"reg_other": {}}}):
			with self.assertRaises(InvalidDataError):
				resolve_pricing_authority("reg_test")

	def test_a_deployment_without_cart_anchors_cannot_price(self) -> None:
		with self.set_conf(ceto_cart={"guest_customer": self.guest}):
			with self.assertRaises(InvalidDataError):
				resolve_pricing_authority("reg_test")


class TestCalculatePrices(PricingTestSuite):
	def test_a_rate_on_the_regions_price_list_serves_the_calculated_price(self) -> None:
		item = self.published_item()
		self.rate(item, 199.5)

		with self.priced():
			prices = calculate_prices({item.name: item.stock_uom}, resolve_pricing_authority("reg_test"))

		price = prices[item.name]
		self.assertEqual(price.calculated_amount, 199.5)
		self.assertEqual(price.original_amount, 199.5)
		self.assertEqual(price.currency_code, self.currency.lower())
		# The flags are facts of the selection: a price-list rate, tax
		# exclusive, promotion untouched.
		for flag in (
			"is_calculated_price_price_list",
			"is_original_price_price_list",
		):
			self.assertIs(getattr(price, flag), True)
		for flag in (
			"is_calculated_price_tax_inclusive",
			"is_original_price_tax_inclusive",
			"is_calculated_price_promotion",
		):
			self.assertIs(getattr(price, flag), False)

	def test_party_and_batch_scoped_rates_never_serve_an_anonymous_read(self) -> None:
		customer_item = self.published_item()
		supplier_item = self.published_item()
		batch_item = self.published_item()
		self.rate(customer_item, 10.0, customer=self.guest)
		supplier_row = self.rate(supplier_item, 10.0)
		frappe.db.set_value(
			"Item Price", supplier_row.name, "supplier", "DEV-NOSUCH-SUPPLIER", update_modified=False
		)
		batch_row = self.rate(batch_item, 10.0)
		frappe.db.set_value(
			"Item Price", batch_row.name, "batch_no", "DEV-NOSUCH-BATCH", update_modified=False
		)

		with self.priced():
			prices = calculate_prices(
				{customer_item.name: "Unit", supplier_item.name: "Unit", batch_item.name: "Unit"},
				resolve_pricing_authority("reg_test"),
			)

		self.assertEqual(prices, {})

	def test_an_out_of_window_rate_never_serves(self) -> None:
		expired_item = self.published_item()
		future_item = self.published_item()
		boundary_item = self.published_item()
		self.rate(expired_item, 10.0, valid_upto=add_days(today(), -1))
		self.rate(future_item, 10.0, valid_from=add_days(today(), 1))
		self.rate(boundary_item, 10.0, valid_from=today(), valid_upto=today())

		with self.priced():
			prices = calculate_prices(
				{expired_item.name: "Unit", future_item.name: "Unit", boundary_item.name: "Unit"},
				resolve_pricing_authority("reg_test"),
			)

		self.assertEqual(set(prices), {boundary_item.name})
		self.assertEqual(prices[boundary_item.name].calculated_amount, 10.0)

	def test_a_rate_on_another_price_list_never_serves(self) -> None:
		item = self.published_item()
		other = f"Dev Other Selling {frappe.generate_hash(length=8)}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": other,
				"currency": self.currency,
				"selling": 1,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		self.fixtures.item_price(item, 99.0, price_list=other)

		with self.priced():
			prices = calculate_prices({item.name: "Unit"}, resolve_pricing_authority("reg_test"))

		self.assertEqual(prices, {})

	def test_the_uom_rule_follows_the_cart_read(self) -> None:
		foreign_uom_item = self.published_item()
		stock_uom_item = self.published_item()
		foreign_uom_item.append("uoms", {"uom": "Hour", "conversion_factor": 1})
		foreign_uom_item.save(ignore_permissions=True)
		self.rate(foreign_uom_item, 20.0, uom="Hour")
		self.rate(stock_uom_item, 20.0, uom="Unit")

		with self.priced():
			prices = calculate_prices(
				{foreign_uom_item.name: "Unit", stock_uom_item.name: "Unit"},
				resolve_pricing_authority("reg_test"),
			)

		# A foreign conversion UOM never replaces the item's stock-UOM rate.
		self.assertEqual(set(prices), {stock_uom_item.name})
		self.assertEqual(prices[stock_uom_item.name].calculated_amount, 20.0)

	def test_the_newest_valid_window_leads(self) -> None:
		item = self.published_item()
		self.rate(item, 10.0, valid_from="2000-01-01", valid_upto="2020-05-31")
		self.rate(item, 20.0, valid_from="2020-06-01", uom="Unit")

		with self.priced():
			prices = calculate_prices(
				{item.name: "Unit"},
				resolve_pricing_authority("reg_test"),
			)

		self.assertEqual(prices[item.name].calculated_amount, 20.0)

	def test_an_unpriced_item_stays_absent_instead_of_a_fabricated_zero(self) -> None:
		item = self.published_item()

		with self.priced():
			prices = calculate_prices({item.name: "Unit"}, resolve_pricing_authority("reg_test"))

		self.assertEqual(prices, {})


class TestPricedProductSurfaces(PricingTestSuite):
	def test_a_region_id_prices_the_variants_surface_through_the_cart_authority(self) -> None:
		item = self.published_item()
		self.rate(item, 199.5)

		with self.priced():
			page = ProductCatalog().variant_page(region_id="reg_test")

		price = page.variants[0].calculated_price
		self.assertEqual(price.calculated_amount, 199.5)
		self.assertEqual(price.original_amount, 199.5)
		self.assertEqual(price.currency_code, self.currency.lower())
		self.assertIs(price.is_calculated_price_price_list, True)

	def test_no_region_serves_the_projection_unpriced(self) -> None:
		item = self.published_item()
		self.rate(item, 199.5)

		with self.priced():
			page = ProductCatalog().variant_page()
			padded = ProductCatalog().variant_page(region_id="   ")

		for variant in (*page.variants, *padded.variants):
			self.assertIsNone(variant.calculated_price)

	def test_an_unpriced_variant_stays_absent_while_its_page_is_priced(self) -> None:
		priced = self.published_item(item_name="Dev Priced", item_code="DEV-PRICE-PRICED")
		unpriced = self.published_item(item_name="Dev Unpriced", item_code="DEV-PRICE-BLANK")
		self.rate(priced, 199.5)

		with self.priced():
			page = ProductCatalog().variant_page(region_id="reg_test")

		prices = {variant.sku: variant.calculated_price for variant in page.variants}
		self.assertEqual(prices[priced.name].calculated_amount, 199.5)
		self.assertIsNone(prices[unpriced.name])

	def test_the_detail_prices_its_variants_the_same_way(self) -> None:
		item = self.published_item()
		self.rate(item, 155.0)

		with self.priced():
			response = ProductCatalog().get(product_public_id(item.name), region_id="reg_test")
			unpriced = ProductCatalog().get(product_public_id(item.name))

		price = response.product.variants[0].calculated_price
		self.assertEqual(price.calculated_amount, 155.0)
		self.assertEqual(get_datetime(item.creation), response.product.created_at)
		self.assertIsNone(unpriced.product.variants[0].calculated_price)
