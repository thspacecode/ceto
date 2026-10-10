"""Fast, DB-free tests for the bootstrap orchestration in ``setup_site``.

Every seeder is replaced by a mock, so these tests can pin the exact seeder
order, the merged report the orchestrator returns, and how ``execute`` turns
keyword overrides into ``BootstrapSettings``. Seeder behavior itself is not
covered here.
"""

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from ceto.data.base_importer import Report
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.bootstrap_dev.setup_site import DEV_BOOTSTRAP_NOTE, SetupSite
from ceto.data.bootstrap_dev.setup_site import execute as setup_site_execute
from ceto.tests.utils import CetoTestSuite

SETUP_SITE = "ceto.data.bootstrap_dev.setup_site"

COMPANY = "Ceto Development Co"
SETTINGS = BootstrapSettings()

# The documented dependency order: site prerequisites first, then the masters
# that are seeded into the resolved company, then the Ceto-owned catalog.
SEEDER_NAMES = (
	"SetupCompany",
	"SetupItemGroups",
	"SetupUoms",
	"SetupWarehouses",
	"SetupCustomers",
	"SetupPriceLists",
	"SetupItems",
	"SetupItemTags",
	"SetupItemPrices",
	"SetupTaxes",
	"SetupCatalog",
)


def report(created=None, updated=None, skipped=None, notes=None) -> Report:
	"""Build a Report with only the buckets a stub cares about."""
	return {
		"created": created or {},
		"updated": updated or {},
		"skipped": skipped or {},
		"notes": notes or [],
	}


SEEDER_REPORTS = {
	"SetupCompany": report(
		created={"Company": [COMPANY]},
		skipped={"Setup Wizard": ["already complete"]},
	),
	"SetupItemGroups": report(created={"Item Group": ["Dev Apparel"]}, notes=["item groups note"]),
	"SetupUoms": report(skipped={"UOM": ["Unit"]}),
	"SetupWarehouses": report(created={"Warehouse": ["Dev Stores"]}),
	"SetupCustomers": report(created={"Customer": ["Ceto Guest"]}),
	"SetupPriceLists": report(created={"Price List": ["Ceto Dev Selling"]}),
	"SetupItems": report(created={"Item": ["DEV-TSHIRT-001", "DEV-HOODIE-001"]}),
	"SetupItemTags": report(
		created={"Tag": ["Dev Summer"], "Tag Link": ["tag 'Dev Summer' on DEV-TSHIRT-001"]},
	),
	"SetupItemPrices": report(
		created={"Item Price": ["DEV-TSHIRT-001"]},
		updated={"Item Price": ["DEV-HOODIE-001"]},
	),
	"SetupTaxes": report(
		created={"Sales Taxes and Charges Template": ["Ceto Dev Sales Taxes"]},
		notes=["taxes note"],
	),
	"SetupCatalog": report(
		created={"Ceto Collection": ["dev-summer-drop"], "Ceto Product Type": ["Dev Apparel"]},
	),
}


@contextmanager
def mocked_pipeline(gateway: MagicMock) -> Iterator[MagicMock]:
	"""Point every seeder name at a ``gateway`` child stub with a canned report."""
	with ExitStack() as stack:
		for name in SEEDER_NAMES:
			seeder = getattr(gateway, name)
			seeder.return_value.make.return_value = SEEDER_REPORTS[name]
			stack.enter_context(patch(f"{SETUP_SITE}.{name}", new=seeder))
		gateway.resolve_company.return_value = COMPANY
		stack.enter_context(patch(f"{SETUP_SITE}.resolve_company", new=gateway.resolve_company))
		yield gateway


class TestSeederOrder(CetoTestSuite):
	def test_seeders_run_once_each_in_documented_order_with_the_resolved_company(self):
		gateway = MagicMock()

		with mocked_pipeline(gateway):
			SetupSite(SETTINGS).make()

		self.assertEqual(
			gateway.mock_calls,
			[
				call.SetupCompany(SETTINGS),
				call.SetupCompany().make(),
				call.resolve_company(SETTINGS),
				call.SetupItemGroups(SETTINGS),
				call.SetupItemGroups().make(),
				call.SetupUoms(SETTINGS),
				call.SetupUoms().make(),
				call.SetupWarehouses(SETTINGS, COMPANY),
				call.SetupWarehouses().make(),
				call.SetupCustomers(SETTINGS),
				call.SetupCustomers().make(),
				call.SetupPriceLists(SETTINGS, COMPANY),
				call.SetupPriceLists().make(),
				call.SetupItems(SETTINGS, COMPANY),
				call.SetupItems().make(),
				call.SetupItemTags(SETTINGS),
				call.SetupItemTags().make(),
				call.SetupItemPrices(SETTINGS, COMPANY),
				call.SetupItemPrices().make(),
				call.SetupTaxes(SETTINGS, COMPANY),
				call.SetupTaxes().make(),
				call.SetupCatalog(SETTINGS),
				call.SetupCatalog().make(),
			],
		)

	def test_every_seeder_is_instantiated_and_run_exactly_once(self):
		gateway = MagicMock()

		with mocked_pipeline(gateway):
			SetupSite().make()

		for name in SEEDER_NAMES:
			seeder = getattr(gateway, name)
			self.assertEqual(seeder.call_count, 1, name)
			seeder.return_value.make.assert_called_once_with()


class TestMergedReport(CetoTestSuite):
	def test_make_merges_every_seeder_report_into_one(self):
		expected = {
			"created": {
				"Company": [COMPANY],
				"Item Group": ["Dev Apparel"],
				"Warehouse": ["Dev Stores"],
				"Customer": ["Ceto Guest"],
				"Price List": ["Ceto Dev Selling"],
				"Item": ["DEV-TSHIRT-001", "DEV-HOODIE-001"],
				"Tag": ["Dev Summer"],
				"Tag Link": ["tag 'Dev Summer' on DEV-TSHIRT-001"],
				"Item Price": ["DEV-TSHIRT-001"],
				"Sales Taxes and Charges Template": ["Ceto Dev Sales Taxes"],
				"Ceto Collection": ["dev-summer-drop"],
				"Ceto Product Type": ["Dev Apparel"],
			},
			"updated": {"Item Price": ["DEV-HOODIE-001"]},
			"skipped": {"Setup Wizard": ["already complete"], "UOM": ["Unit"]},
			"notes": [DEV_BOOTSTRAP_NOTE, "item groups note", "taxes note"],
		}
		site = SetupSite(SETTINGS)

		with mocked_pipeline(MagicMock()):
			returned = site.make()

		self.assertEqual(returned, expected)
		self.assertIs(returned, site.report)
		self.assertEqual(returned["notes"][0], DEV_BOOTSTRAP_NOTE)


class TestExecuteOverrides(CetoTestSuite):
	def test_keyword_overrides_replace_matching_settings_fields_only(self):
		with patch(f"{SETUP_SITE}.SetupSite") as setup_site:
			returned = setup_site_execute(company="Acme Co", tax_rate=Decimal("0.07"))

		self.assertEqual(setup_site.call_count, 1)
		settings = setup_site.call_args[0][0]
		self.assertIsInstance(settings, BootstrapSettings)
		self.assertEqual(settings.company, "Acme Co")
		self.assertEqual(settings.tax_rate, Decimal("0.07"))
		self.assertEqual(settings.company_name, "Ceto Development Co")
		self.assertEqual(settings.selling_price_list, "Ceto Dev Selling")
		setup_site.return_value.make.assert_called_once_with()
		self.assertIs(returned, setup_site.return_value.make.return_value)

	def test_without_overrides_the_default_settings_are_used(self):
		with patch(f"{SETUP_SITE}.SetupSite") as setup_site:
			setup_site_execute()

		self.assertEqual(setup_site.call_args[0][0], BootstrapSettings())
		setup_site.return_value.make.assert_called_once_with()

	def test_unknown_overrides_are_rejected_before_anything_runs(self):
		with patch(f"{SETUP_SITE}.SetupSite") as setup_site:
			with self.assertRaises(TypeError) as raised:
				setup_site_execute(not_a_bootstrap_setting="x")

		self.assertIn("not_a_bootstrap_setting", str(raised.exception))
		setup_site.assert_not_called()
