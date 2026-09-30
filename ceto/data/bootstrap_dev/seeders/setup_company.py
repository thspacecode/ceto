"""Ensure the site and company prerequisites required by commerce master data."""

import erpnext
import frappe
from frappe import _

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import BootstrapError


def resolve_company(settings: BootstrapSettings) -> str:
	"""Resolve the company the bootstrap seeds into, or fail with a clear message."""
	company = settings.company or erpnext.get_default_company()
	if not company or not frappe.db.exists("Company", company):
		msg = _(
			"No default Company found. Complete the site setup wizard, or pass a "
			"'company' setting, before bootstrapping commerce data."
		)
		frappe.throw(msg, BootstrapError)
	return company


class SetupCompany(BaseImporter):
	"""Complete the setup wizard on fresh sites and resolve the target company.

	The wizard is the safe prerequisite path: ERPNext creates the company with
	its standard chart of accounts, fiscal year, root warehouses, default price
	lists, UOMs, and selling defaults. Sites that are already set up are only
	validated, never reconfigured.
	"""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		wizard_ran = False
		if not frappe.is_setup_complete():
			self.complete_setup_wizard()
			wizard_ran = True
		else:
			self.record_change("skipped", "Setup Wizard", "already complete")

		company = resolve_company(self.settings)
		self.record_change("created" if wizard_ran else "skipped", "Company", company)
		return self.report

	def complete_setup_wizard(self) -> None:
		from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

		setup_complete(
			{
				"currency": self.settings.wizard_currency,
				"country": self.settings.wizard_country,
				"timezone": self.settings.wizard_timezone,
				"language": self.settings.wizard_language,
				"company_name": self.settings.company_name,
				"company_abbr": self.settings.company_abbr,
				"chart_of_accounts": self.settings.wizard_chart_of_accounts,
				"fy_start_date": self.settings.fiscal_year_start,
				"fy_end_date": self.settings.fiscal_year_end,
				"setup_demo": 0,
			}
		)


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the site/company prerequisite seeder."""
	return SetupCompany(settings or BootstrapSettings()).make()
