"""Thin adapter over the committed ``ceto.data.bootstrap_dev`` commerce baseline.

The Company, guest Customer, selling Price List, and catalog items are owned by
the bootstrap and imported once through ``ceto.tests.utils``; this module creates
no commerce masters. It only derives the cart ``ceto_cart`` configuration from
the same bootstrap settings, exposes the bootstrap items with their committed
rates, and layers one idempotent, test-only tax template on top so cart totals
carry a meaningful rate. Currency is deliberately omitted:
``CartConfiguration`` resolves it from the selling price list, which the
bootstrap creates in the company currency.
"""

from typing import Any

import frappe

from ceto.data.bootstrap_dev.dataset import ITEM_PRICES
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.utils import boot_strap_test_master_data

TEST_TAX_ACCOUNT = "Ceto Test Cart Tax"
TEST_TAX_TEMPLATE_TITLE = "Ceto Test Cart Taxes"
TAX_RATE = 10.0


def _bootstrap_rate(item_code: str) -> float:
	"""Return the bootstrap selling rate for ``item_code`` as a float."""
	for seed in ITEM_PRICES:
		if seed.item_code == item_code:
			return float(seed.price_list_rate)
	raise ValueError(f"{item_code} is not priced by the ceto.data.bootstrap_dev dataset")


ITEM_PRICE = _bootstrap_rate("DEV-TSHIRT-001")
ITEM_PRICE_B = _bootstrap_rate("DEV-HOODIE-001")


class CartTestData:
	"""Expose the bootstrap commerce masters as cart test configuration."""

	_shared: "CartTestData | None" = None

	@classmethod
	def shared(cls) -> "CartTestData":
		"""One committed master dataset per test process.

		Creating a Company (chart of accounts, defaults, warehouses) costs
		~24s, which dominated every test when masters were built per test
		method. Masters are read-only inputs for the tests, so a single
		committed instance is shared by all of them; per-test documents
		are still isolated by the suite's rollback teardown.
		"""
		if cls._shared is None:
			cls._shared = cls()
			frappe.db.commit()
		return cls._shared

	def __init__(self) -> None:
		self.settings: BootstrapSettings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(self.settings)
		# Same identity rule as the bootstrap: the guest is located by
		# customer_name, never by docname.
		self.customer = frappe.db.get_value("Customer", {"customer_name": self.settings.guest_customer_name})
		self.price_list = self.settings.selling_price_list
		# Catalog items and their rates come verbatim from the bootstrap.
		self.item = "DEV-TSHIRT-001"
		self.other_item = "DEV-HOODIE-001"
		self.taxes_and_charges = self._make_test_tax_template()

	@property
	def configuration(self) -> dict[str, Any]:
		return {
			"guest_customer": self.customer,
			"company": self.company,
			"selling_price_list": self.price_list,
			"taxes_and_charges": self.taxes_and_charges,
			"territory": self.settings.guest_territory,
			"default_region_id": "reg_test",
			"default_sales_channel_id": "sc_test",
		}

	def _make_test_tax_template(self) -> str:
		"""Layer a fixed-name 10% tax template over the bootstrap baseline.

		The bootstrap ships only zero-rated masters, and cart tests still need a
		tax rate worth asserting on. The template is anchored on a dedicated
		test account and reused whenever it already exists, so re-instantiating
		``CartTestData`` converges instead of duplicating master data. Freshly
		created records are committed at once because the router rolls back the
		open transaction when it converts a failed request into an error
		response, and the template must outlive that rollback.
		"""
		company = self.company
		account = frappe.db.get_value(
			"Account", {"account_name": TEST_TAX_ACCOUNT, "company": company, "is_group": 0}
		)
		if not account:
			abbr = frappe.db.get_value("Company", company, "abbr")
			account = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": TEST_TAX_ACCOUNT,
						"parent_account": f"Duties and Taxes - {abbr}",
						"company": company,
						"account_type": "Tax",
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
			frappe.db.commit()  # nosemgrep
		template = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"title": TEST_TAX_TEMPLATE_TITLE, "company": company}
		)
		if template:
			return template
		template = (
			frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": TEST_TAX_TEMPLATE_TITLE,
					"company": company,
					"is_default": 0,
					"taxes": [
						{
							"charge_type": "On Net Total",
							"account_head": account,
							"rate": TAX_RATE,
							"description": TEST_TAX_ACCOUNT,
							"included_in_print_rate": 0,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.commit()  # nosemgrep
		return template
