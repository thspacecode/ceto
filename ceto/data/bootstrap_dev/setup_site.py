"""Fixed orchestration for the Ceto development bootstrap.

Runs explicitly; nothing in Ceto installs or migrates this data automatically:

	bench --site <site> execute ceto.data.bootstrap_dev.setup_site.execute
"""

from dataclasses import replace
from typing import Any

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.seeders.setup_company import SetupCompany, resolve_company
from ceto.data.bootstrap_dev.seeders.setup_customers import SetupCustomers
from ceto.data.bootstrap_dev.seeders.setup_item_groups import SetupItemGroups
from ceto.data.bootstrap_dev.seeders.setup_item_prices import SetupItemPrices
from ceto.data.bootstrap_dev.seeders.setup_items import SetupItems
from ceto.data.bootstrap_dev.seeders.setup_price_lists import SetupPriceLists
from ceto.data.bootstrap_dev.seeders.setup_taxes import SetupTaxes
from ceto.data.bootstrap_dev.seeders.setup_uoms import SetupUoms
from ceto.data.bootstrap_dev.seeders.setup_warehouses import SetupWarehouses
from ceto.data.bootstrap_dev.settings import BootstrapSettings

DEV_BOOTSTRAP_NOTE = "Development bootstrap: every seeded record is non-production sample data."


class SetupSite(BaseImporter):
	"""Bring a disposable development or test site to a usable commerce baseline.

	Each run converges: records already at their expected values are reported
	as skipped, only seeder-owned fields are ever written, and ambiguous
	identities abort the run instead of guessing.
	"""

	def __init__(self, settings: BootstrapSettings | None = None) -> None:
		super().__init__()
		self.settings = settings or BootstrapSettings()

	def make(self) -> Report:
		self.record_note(DEV_BOOTSTRAP_NOTE)

		self.merge_report(SetupCompany(self.settings).make())
		company = resolve_company(self.settings)

		self.merge_report(SetupItemGroups(self.settings).make())
		self.merge_report(SetupUoms(self.settings).make())
		self.merge_report(SetupWarehouses(self.settings, company).make())
		self.merge_report(SetupCustomers(self.settings).make())
		self.merge_report(SetupPriceLists(self.settings, company).make())
		self.merge_report(SetupItems(self.settings, company).make())
		self.merge_report(SetupItemPrices(self.settings, company).make())
		self.merge_report(SetupTaxes(self.settings, company).make())
		return self.report


def execute(**overrides: Any) -> Report:
	"""Bench entry point; keyword arguments override ``BootstrapSettings`` fields."""
	settings = replace(BootstrapSettings(), **overrides) if overrides else BootstrapSettings()
	return SetupSite(settings).make()
