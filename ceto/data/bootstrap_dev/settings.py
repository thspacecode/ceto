"""Centralised, overridable values for the Ceto development bootstrap.

Every default in this module is intentionally non-production: it exists to make
a disposable development or test site usable. No values are read from site
config or secrets; operators override fields explicitly through
``ceto.data.bootstrap_dev.setup_site.execute`` keyword arguments.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class BootstrapSettings:
	"""Values used to bootstrap a minimal viable ERPNext commerce dataset."""

	# Site prerequisites, applied only when the setup wizard has not run yet.
	wizard_country: str = "United States"
	wizard_language: str = "English"
	wizard_timezone: str = "America/New_York"
	wizard_currency: str = "USD"
	wizard_chart_of_accounts: str = "Standard"
	company_name: str = "Ceto Development Co"
	company_abbr: str = "CDEV"

	# Existing sites may pin the target company explicitly; empty resolves to
	# the site default company.
	company: str = ""

	# Commerce master data owned by the bootstrap.
	selling_price_list: str = "Ceto Dev Selling"
	# Item Price defaults valid_from to Today. A fixed date gives bootstrap
	# prices a stable identity across runs and keeps them active for dev data.
	item_price_valid_from: str = "2000-01-01"
	guest_customer_name: str = "Ceto Guest"
	guest_customer_group: str = "Individual"
	guest_territory: str = "Rest Of The World"
	sales_taxes_template_title: str = "Ceto Dev Sales Taxes"
	tax_rate: Decimal = Decimal("0")

	@property
	def fiscal_year_start(self) -> str:
		return f"{datetime.now().year}-01-01"

	@property
	def fiscal_year_end(self) -> str:
		return f"{datetime.now().year}-12-31"
