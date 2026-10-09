"""Reference regions: config-backed projections with no DocType.

``RegionDirectory`` projects the ``ceto_cart.regions`` site configuration —
no new DocType — onto the pinned ``StoreRegion`` contract. The tests pin the
servability gate (existing Company, existing selling Price List, resolvable
currency), the overlay from the top-level defaults, the deterministic
ordering and pagination, and the timestamps policy: config-backed regions
never carry fabricated timestamps.
"""

import frappe

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.reference.regions import RegionDirectory
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data

REGION_LIST_DEFAULT_LIMIT = 20
CONFLICT_CURRENCY = "XTS"


class TestRegionDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.price_list = settings.selling_price_list
		self.currency = frappe.db.get_value("Price List", self.price_list, "currency")

	def test_lists_a_valid_region_with_the_pinned_projection(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				"reg_test": {
					"name": "Test Region",
					"company": self.company,
					"selling_price_list": self.price_list,
				}
			},
		}
		with self.set_conf(ceto_cart=configuration):
			page = RegionDirectory().list()
		self.assertEqual(page.count, 1)
		self.assertEqual(page.offset, 0)
		self.assertEqual(page.limit, REGION_LIST_DEFAULT_LIMIT)
		(region,) = page.regions
		self.assertEqual(region.id, "reg_test")
		# The optional ``name`` config key (a Ceto extension) is served; the
		# region id is the deterministic fallback name.
		self.assertEqual(region.name, "Test Region")
		self.assertEqual(region.currency_code, (self.currency or "").lower())
		self.assertTrue(region.automatic_taxes)
		self.assertIsNone(region.countries)
		self.assertIsNone(region.metadata)
		# Config-backed: no fabricated timestamps.
		self.assertIsNone(region.created_at)
		self.assertIsNone(region.updated_at)

	def test_region_entry_without_name_falls_back_to_the_region_id(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {"reg_test": {"company": self.company, "selling_price_list": self.price_list}},
		}
		with self.set_conf(ceto_cart=configuration):
			(region,) = RegionDirectory().servable()
		self.assertEqual(region.name, "reg_test")

	def test_entry_overlays_the_top_level_defaults(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {"reg_test": {"name": "Inherited"}},
		}
		with self.set_conf(ceto_cart=configuration):
			(region,) = RegionDirectory().servable()
		self.assertEqual(region.id, "reg_test")
		self.assertEqual(region.currency_code, (self.currency or "").lower())

	def test_regions_order_deterministically_by_region_id(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				"reg_b": {"company": self.company, "selling_price_list": self.price_list},
				"reg_a": {"company": self.company, "selling_price_list": self.price_list},
				"reg_c": {"company": self.company, "selling_price_list": self.price_list},
			},
		}
		with self.set_conf(ceto_cart=configuration):
			page = RegionDirectory().list()
		self.assertEqual([region.id for region in page.regions], ["reg_a", "reg_b", "reg_c"])
		self.assertEqual(page.count, 3)

	def test_unservable_regions_are_masked(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				"reg_ok": {"company": self.company, "selling_price_list": self.price_list},
				# Unknown company anchor.
				"reg_company": {"company": "Missing Co", "currency": self.currency},
				# Unknown price list anchor.
				"reg_price_list": {"selling_price_list": "Missing Selling", "currency": self.currency},
				# Currency neither configured nor resolvable from the price list.
				"reg_currency": {
					"company": self.company,
					"selling_price_list": self.price_list,
					"currency": "ZZZ",
				},
			},
		}
		with self.set_conf(ceto_cart=configuration):
			directory = RegionDirectory()
			page = directory.list()
			self.assertEqual([region.id for region in page.regions], ["reg_ok"])
			self.assertEqual(page.count, 1)
			with self.assertRaises(RouteNotFoundError):
				directory.get("reg_currency")

	def test_region_whose_currency_conflicts_with_its_price_list_is_masked(self):
		# An explicit currency that conflicts with the selling Price List's
		# own currency resolves no usable cart (carts price in the Price
		# List's currency), so the region never surfaces — even though both
		# anchors and the Currency record exist.
		self._make_currency()
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				"reg_ok": {"company": self.company, "selling_price_list": self.price_list},
				"reg_conflict": {
					"company": self.company,
					"selling_price_list": self.price_list,
					"currency": CONFLICT_CURRENCY,
				},
			},
		}
		with self.set_conf(ceto_cart=configuration):
			directory = RegionDirectory()
			self.assertEqual([region.id for region in directory.servable()], ["reg_ok"])
			with self.assertRaises(RouteNotFoundError):
				directory.get("reg_conflict")

	def test_without_region_config_the_list_is_empty(self):
		configuration = {"company": self.company, "selling_price_list": self.price_list}
		with self.set_conf(ceto_cart=configuration):
			page = RegionDirectory().list()
		self.assertEqual(page.regions, [])
		self.assertEqual(page.count, 0)

	def test_pagination_slices_and_echoes_the_effective_window(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {
				f"reg_{index}": {"company": self.company, "selling_price_list": self.price_list}
				for index in range(5)
			},
		}
		with self.set_conf(ceto_cart=configuration):
			page = RegionDirectory().list(offset=2, limit=2)
		self.assertEqual([region.id for region in page.regions], ["reg_2", "reg_3"])
		self.assertEqual(page.count, 5)
		self.assertEqual(page.offset, 2)
		self.assertEqual(page.limit, 2)

	def test_detail_resolves_one_region(self):
		configuration = {
			"company": self.company,
			"selling_price_list": self.price_list,
			"regions": {"reg_test": {"company": self.company, "selling_price_list": self.price_list}},
		}
		with self.set_conf(ceto_cart=configuration):
			response = RegionDirectory().get("reg_test")
			with self.assertRaises(RouteNotFoundError):
				RegionDirectory().get("reg_unknown")
		self.assertEqual(response.region.id, "reg_test")

	def _make_currency(self) -> None:
		"""Ensure a second, existing Currency record for the conflict case."""
		if frappe.db.exists("Currency", CONFLICT_CURRENCY):
			return
		frappe.get_doc(
			{
				"doctype": "Currency",
				"__newname": CONFLICT_CURRENCY,
				"currency_name": CONFLICT_CURRENCY,
				"enabled": 1,
				"number_format": "#,###.##",
			}
		).insert()
