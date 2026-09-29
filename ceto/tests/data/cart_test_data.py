import uuid
from datetime import date
from typing import Any

import frappe


class CartTestData:
	"""Create isolated ERPNext masters for cart integration tests."""

	def __init__(self) -> None:
		self.suffix = uuid.uuid4().hex[:8]
		self.company = self._make_company()
		self.customer = self._make_customer()
		self.price_list = self._make_price_list()

	@property
	def configuration(self) -> dict[str, Any]:
		return {
			"guest_customer": self.customer,
			"company": self.company.name,
			"selling_price_list": self.price_list,
			"territory": "All Territories",
			"currency": "USD",
			"default_region_id": "reg_test",
			"default_sales_channel_id": "sc_test",
		}

	def _make_company(self):
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "__newname": "Transit"}).insert(
				ignore_permissions=True
			)
		company = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": f"Ceto Cart Co {self.suffix}",
				"abbr": f"CC{self.suffix[:4]}".upper(),
				"country": "United States",
				"default_currency": "USD",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert(ignore_permissions=True)
		self._make_fiscal_year(company.name)
		return company

	def _make_fiscal_year(self, company: str) -> None:
		year = date.today().year
		name = f"{year} ({company})"
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": name,
				"year_start_date": f"{year}-01-01",
				"year_end_date": f"{year}-12-31",
				"companies": [{"company": company}],
			}
		).insert(ignore_permissions=True)

	def _make_customer(self) -> str:
		self._make_tree_master("Territory", "All Territories", "territory_name")
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		if not customer_group:
			customer_group = (
				frappe.get_doc(
					{
						"doctype": "Customer Group",
						"customer_group_name": f"Individual {self.suffix}",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		return (
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": f"Guest {self.suffix}",
					"customer_type": "Individual",
					"customer_group": customer_group,
					"territory": "All Territories",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_price_list(self) -> str:
		name = f"Ceto Selling {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
				"currency": "USD",
			}
		).insert(ignore_permissions=True)
		return name

	@staticmethod
	def _make_tree_master(doctype: str, name: str, fieldname: str) -> None:
		if not frappe.db.exists(doctype, name):
			frappe.get_doc({"doctype": doctype, fieldname: name, "is_group": 1}).insert(
				ignore_permissions=True
			)
