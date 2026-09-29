import uuid
from datetime import date
from typing import Any

import frappe
from frappe.utils import today

ITEM_PRICE = 100.0
ITEM_PRICE_B = 50.0
TAX_RATE = 10.0


class CartTestData:
	"""Create isolated ERPNext masters for cart integration tests."""

	def __init__(self) -> None:
		self.suffix = uuid.uuid4().hex[:8]
		self.company = self._make_company()
		self.customer = self._make_customer()
		self.price_list = self._make_price_list()
		self.item = self._make_item(price=ITEM_PRICE)
		self.other_item = self._make_item(code_suffix="-B", price=ITEM_PRICE_B)
		self.taxes_and_charges = self._make_tax_template()

	@property
	def configuration(self) -> dict[str, Any]:
		return {
			"guest_customer": self.customer,
			"company": self.company.name,
			"selling_price_list": self.price_list,
			"taxes_and_charges": self.taxes_and_charges,
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
		if frappe.db.exists("Fiscal Year", name):
			return
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

	def _make_item(self, code_suffix: str = "", price: float = ITEM_PRICE) -> str:
		company = self.company.name
		abbr = frappe.db.get_value("Company", company, "abbr")
		cost_center = frappe.db.get_value("Company", company, "cost_center")
		if not frappe.db.exists("Item Group", "All Item Groups"):
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("UOM", "Nos"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
		item_code = f"CETO-CART-ITEM{code_suffix}-{self.suffix}"
		item_name = f"Ceto Cart Item{code_suffix} {self.suffix}"
		item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": item_code,
					"item_name": item_name,
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"item_defaults": [
						{
							"company": company,
							"income_account": f"Sales - {abbr}",
							"expense_account": f"Cost of Goods Sold - {abbr}",
							"selling_cost_center": cost_center,
							"buying_cost_center": cost_center,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item,
				"item_name": item_name,
				"price_list": self.price_list,
				"currency": "USD",
				"price_list_rate": price,
				"valid_from": today(),
				"valid_upto": None,
			}
		).insert(ignore_permissions=True)
		return item

	def _make_tax_template(self) -> str:
		company = self.company.name
		abbr = frappe.db.get_value("Company", company, "abbr")
		account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": f"Cart Tax {self.suffix}",
				"parent_account": f"Duties and Taxes - {abbr}",
				"company": company,
				"account_type": "Tax",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		return (
			frappe.get_doc(
				{
					"doctype": "Sales Taxes and Charges Template",
					"title": f"Ceto Cart Tax {self.suffix}",
					"company": company,
					"is_default": 0,
					"taxes": [
						{
							"charge_type": "On Net Total",
							"account_head": account.name,
							"rate": TAX_RATE,
							"description": f"Cart Tax {self.suffix}",
							"included_in_print_rate": 0,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@staticmethod
	def _make_tree_master(doctype: str, name: str, fieldname: str) -> None:
		if not frappe.db.exists(doctype, name):
			frappe.get_doc({"doctype": doctype, fieldname: name, "is_group": 1}).insert(
				ignore_permissions=True
			)
