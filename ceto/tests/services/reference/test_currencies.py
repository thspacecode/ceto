"""Reference currencies: scoped to valid configured commerce regions.

``CurrencyDirectory`` projects the ERPNext ``Currency`` records the servable
regions reference — never the whole currency table. The tests pin the
scoping, the deduplication and lowercase Medusa codes, the ERPNext-derived
metadata (fraction digits from ``number_format``, rounding from
``smallest_currency_fraction_value``), the real record timestamps, and the
masking of unreferenced currencies.
"""

import frappe

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.reference.currencies import CurrencyDirectory
from ceto.services.reference.regions import RegionDirectory
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data

TEST_CURRENCY = "XTS"
TEST_DECIMAL_CURRENCY = "XJP"


class TestCurrencyDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.price_list = settings.selling_price_list
		self.currency = frappe.db.get_value("Price List", self.price_list, "currency")
		self.extra_currency = self._make_currency(TEST_CURRENCY, "#,###.##")
		self.zero_fraction_currency = self._make_currency(TEST_DECIMAL_CURRENCY, "#,###")
		self.extra_price_list = self._make_price_list("Ceto Ref XTS Selling", TEST_CURRENCY)
		self.zero_fraction_price_list = self._make_price_list("Ceto Ref XJP Selling", TEST_DECIMAL_CURRENCY)

	def test_lists_only_the_referenced_currencies(self):
		with self.set_conf(ceto_cart=self._configuration()):
			page = CurrencyDirectory().list()
		self.assertEqual(
			[entry.code for entry in page.currencies],
			sorted({self.currency.lower(), TEST_CURRENCY.lower(), TEST_DECIMAL_CURRENCY.lower()}),
		)
		self.assertEqual(page.count, 3)
		self.assertEqual(page.offset, 0)
		self.assertEqual(page.limit, 50)

	def test_never_serves_unreferenced_currencies(self):
		with self.set_conf(ceto_cart=self._configuration()):
			codes = {entry.code for entry in CurrencyDirectory().list().currencies}
			self.assertNotIn("eur", codes)
			with self.assertRaises(RouteNotFoundError):
				CurrencyDirectory().get("eur")

	def test_projects_erpnext_currency_metadata(self):
		with self.set_conf(ceto_cart=self._configuration()):
			response = CurrencyDirectory().get(TEST_CURRENCY.lower())
		entry = response.currency
		self.assertEqual(entry.code, TEST_CURRENCY.lower())
		self.assertEqual(entry.name, TEST_CURRENCY)
		# Fraction digits derive from the ERPNext number format; rounding from
		# the smallest currency fraction value.
		self.assertEqual(entry.decimal_digits, 2)
		self.assertEqual(entry.rounding, 0.01)
		# No native-vs-plain symbol distinction exists in ERPNext: never fabricated.
		self.assertIsNone(entry.symbol_native)
		# Real record timestamps, not config projections.
		self.assertIsNotNone(entry.created_at)
		self.assertIsNotNone(entry.updated_at)
		self.assertIsNone(entry.deleted_at)

	def test_zero_fraction_currency_projects_zero_digits_and_unset_rounding(self):
		with self.set_conf(ceto_cart=self._configuration()):
			response = CurrencyDirectory().get(TEST_DECIMAL_CURRENCY.lower())
		entry = response.currency
		self.assertEqual(entry.decimal_digits, 0)
		self.assertIsNone(entry.rounding)

	def test_deduplicates_currencies_shared_by_regions(self):
		configuration = self._configuration()
		configuration["regions"]["reg_again"] = {
			"company": self.company,
			"selling_price_list": self.extra_price_list,
		}
		with self.set_conf(ceto_cart=configuration):
			page = CurrencyDirectory().list()
		self.assertEqual(page.count, 3)

	def test_pagination_slices_the_deduplicated_page(self):
		with self.set_conf(ceto_cart=self._configuration()):
			page = CurrencyDirectory().list(offset=1, limit=1)
		self.assertEqual(page.count, 3)
		self.assertEqual(page.offset, 1)
		self.assertEqual(page.limit, 1)
		self.assertEqual(len(page.currencies), 1)

	def test_no_regions_means_no_currencies(self):
		configuration = {"company": self.company, "selling_price_list": self.price_list}
		with self.set_conf(ceto_cart=configuration):
			page = CurrencyDirectory().list()
		self.assertEqual(page.currencies, [])
		self.assertEqual(page.count, 0)

	def test_a_missing_currency_record_never_breaks_the_list(self):
		# The region gate hides a region whose currency record is gone, so the
		# currency list can never reference a projection-less code.
		configuration = self._configuration()
		configuration["regions"]["reg_ghost"] = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"currency": "ZZZ",
		}
		with self.set_conf(ceto_cart=configuration):
			codes = {entry.code for entry in CurrencyDirectory().list().currencies}
		self.assertNotIn("zzz", codes)

	def test_currency_scoping_follows_the_region_gate(self):
		with self.set_conf(ceto_cart=self._configuration()):
			region = RegionDirectory().get("reg_xts").region
			response = CurrencyDirectory().get(region.currency_code)
		self.assertEqual(response.currency.code, region.currency_code)

	def _configuration(self) -> dict:
		return {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				"reg_base": {"company": self.company, "selling_price_list": self.price_list},
				"reg_xts": {"company": self.company, "selling_price_list": self.extra_price_list},
				"reg_xjp": {"company": self.company, "selling_price_list": self.zero_fraction_price_list},
			},
		}

	def _make_currency(self, code: str, number_format: str) -> str:
		if frappe.db.exists("Currency", code):
			return code
		frappe.get_doc(
			{
				"doctype": "Currency",
				"__newname": code,
				"currency_name": code,
				"enabled": 1,
				"symbol": "Ŧ",
				"smallest_currency_fraction_value": 0.01 if "." in number_format else 0,
				"number_format": number_format,
			}
		).insert()
		return code

	def _make_price_list(self, name: str, currency: str) -> str:
		if frappe.db.exists("Price List", name):
			return name
		frappe.get_doc(
			{
				"doctype": "Price List",
				"__newname": name,
				"price_list_name": name,
				"currency": currency,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
			}
		).insert()
		return name
