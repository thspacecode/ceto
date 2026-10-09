"""The shared ``ceto_cart`` parser: one config shape, one reader.

``ceto.config.cart`` is the only place that parses the private cart site
configuration. The cart service (``CartConfiguration.resolve``) and the
reference-data services (``RegionDirectory``) must never drift, so these
tests pin the parser semantics and the one rule both consumers share:
which currency a configured region resolves to.
"""

import frappe

from ceto.config.cart import (
	cart_settings,
	default_region_id,
	mapped_settings,
	region_entries,
)
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.configuration import CartConfiguration
from ceto.services.reference.regions import RegionDirectory
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data

SETTINGS = {
	"guest_customer": "Webshop Guest",
	"company": "Example Co",
	"selling_price_list": "Selling",
	"currency": "USD",
	"default_region_id": "reg_us",
	"regions": {
		"reg_us": {"company": "US Co", "selling_price_list": "US Selling"},
		"reg_eu": {"currency": "EUR"},
	},
}


class TestCartConfigParser(CetoTestSuite):
	def test_reads_the_private_site_configuration(self):
		with self.set_conf(ceto_cart=SETTINGS):
			self.assertEqual(cart_settings(), SETTINGS)

	def test_absent_mapping_disables_the_keyed_lookup(self):
		self.assertEqual(mapped_settings(SETTINGS, "sales_channels", "sc_web", "sales channel"), {})

	def test_present_mapping_rejects_unknown_keys(self):
		with self.assertRaises(InvalidDataError):
			mapped_settings(SETTINGS, "regions", "reg_xx", "region")
		with self.assertRaises(InvalidDataError):
			mapped_settings(SETTINGS, "regions", None, "region")

	def test_present_mapping_returns_the_entry(self):
		self.assertEqual(
			mapped_settings(SETTINGS, "regions", "reg_us", "region"),
			{"company": "US Co", "selling_price_list": "US Selling"},
		)

	def test_region_entries_and_default_region(self):
		self.assertEqual(region_entries(SETTINGS), SETTINGS["regions"])
		self.assertEqual(default_region_id(SETTINGS), "reg_us")
		self.assertIsNone(default_region_id({}))


class TestSharedRegionCurrencyResolution(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.price_list = settings.selling_price_list
		self.settings = {
			"guest_customer": settings.guest_customer_name,
			"company": self.company,
			"selling_price_list": self.price_list,
			"default_region_id": "reg_test",
			"regions": {
				"reg_test": {
					"company": self.company,
					"selling_price_list": self.price_list,
				}
			},
		}

	def test_cart_and_reference_data_resolve_the_same_region_currency(self):
		with self.set_conf(ceto_cart=self.settings):
			configuration = CartConfiguration.resolve()
			regions = RegionDirectory().servable()
		self.assertEqual(configuration.region_id, "reg_test")
		self.assertEqual([region.id for region in regions], ["reg_test"])
		self.assertEqual(regions[0].currency_code, configuration.currency.lower())

	def test_unknown_region_fails_the_cart_but_masks_the_reference_list(self):
		with self.set_conf(ceto_cart=self.settings):
			with self.assertRaises(InvalidDataError):
				CartConfiguration.resolve(region_id="reg_bad")
			# The reference list never raises on a bad region; the region
			# simply is not servable (no cart could use it either).
			self.assertEqual([region.id for region in RegionDirectory().servable()], ["reg_test"])
