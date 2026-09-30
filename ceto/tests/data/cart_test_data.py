"""Thin adapter over the committed ``ceto.data.bootstrap_dev`` commerce baseline.

The Company, guest Customer, and selling Price List are owned by the bootstrap
and imported once through ``ceto.tests.utils``; this module creates no masters.
It only derives the cart ``ceto_cart`` configuration from the same bootstrap
settings, so tests exercise the records a bootstrapped development site has.
Currency is deliberately omitted: ``CartConfiguration`` resolves it from the
selling price list, which the bootstrap creates in the company currency.
"""

from typing import Any

import frappe

from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.utils import boot_strap_test_master_data


class CartTestData:
	"""Expose the bootstrap commerce masters as cart test configuration."""

	def __init__(self) -> None:
		self.settings: BootstrapSettings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(self.settings)
		# Same identity rule as the bootstrap: the guest is located by
		# customer_name, never by docname.
		self.customer = frappe.db.get_value("Customer", {"customer_name": self.settings.guest_customer_name})
		self.price_list = self.settings.selling_price_list

	@property
	def configuration(self) -> dict[str, Any]:
		return {
			"guest_customer": self.customer,
			"company": self.company,
			"selling_price_list": self.price_list,
			"territory": self.settings.guest_territory,
			"default_region_id": "reg_test",
			"default_sales_channel_id": "sc_test",
		}
