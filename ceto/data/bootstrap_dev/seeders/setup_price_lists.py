"""Seed the selling price list used by the storefront."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import BootstrapError


class SetupPriceLists(BaseImporter):
	"""Seed the Dev selling price list in the company currency.

	The ERPNext-standard price lists are left untouched; storefront pricing
	points at this bootstrap-owned list.
	"""

	def __init__(self, settings: BootstrapSettings, company: str) -> None:
		super().__init__()
		self.settings = settings
		self.company = company

	def make(self) -> Report:
		currency = frappe.get_cached_value("Company", self.company, "default_currency")
		if not currency:
			msg = f"Company {self.company} has no default currency."
			frappe.throw(msg, BootstrapError)

		name = self.settings.selling_price_list
		owned = {
			"currency": currency,
			"enabled": 1,
			"selling": 1,
			"buying": 0,
		}
		if frappe.db.exists("Price List", name):
			doc = frappe.get_doc("Price List", name)
			self.update_and_record(doc, owned, "Price List", name)
		else:
			doc = frappe.new_doc("Price List")
			doc.price_list_name = name
			self.create_and_record(doc, owned, "Price List", name)
		return self.report


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the price list seeder."""
	resolved = settings or BootstrapSettings()
	return SetupPriceLists(resolved, resolve_company(resolved)).make()
