"""Integration proof: Shopping Cart Quotation -> Sales Order via ERPNext mapper.

Runs against real ERPNext behaviour on ``default.site`` inside a single
rolled-back transaction (no mocks of calculations or core):

* unique test masters (Company, Item Group, Territory, UOM, Customer, Item,
  selling Price List + Item Price),
* a draft ``order_type="Shopping Cart"`` Quotation with one priced item,
* a real additional discount as coupon-equivalent
  (``additional_discount_percentage`` on Net Total - see the limitation note
  below) and real appended tax + shipping charge rows in the
  ``taxes`` child table, the shipping row identified by description,
* ERPNext's own ``calculate_taxes_and_totals`` produces the totals,
* the Quotation is submitted, then mapped via
  ``ceto.services.carts.conversion`` into an inserted + submitted Sales Order
  with customer / item / order_type / totals and Quotation-item linkage
  assertions.

Limitation (documented, as encountered): ERPNext has no direct copy of a
``Coupon Code`` (or Pricing Rule) master onto the Sales Order, and a
``Shipping Rule`` master is not guaranteed to survive the mapper verbatim.
This proof therefore materialises the coupon as a genuine document-level
additional discount and the shipping as a genuine ``Actual`` charges row, both
of which ERPNext copies natively into the Sales Order.
"""

import unittest
import uuid
from datetime import date, timedelta

import frappe
from frappe.utils import flt, today

from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.tests.testsuite import CetoTestSuite

RATE = 1000.0
QTY = 3
DISCOUNT_PERCENTAGE = 10.0
TAX_PERCENTAGE = 10.0
SHIPPING_AMOUNT = 150.0
GROSS = RATE * QTY  # 3000
DISCOUNT_AMOUNT = GROSS * DISCOUNT_PERCENTAGE / 100  # 300
NET_TOTAL = GROSS - DISCOUNT_AMOUNT  # 2700
TAX_AMOUNT = NET_TOTAL * TAX_PERCENTAGE / 100  # 270
GRAND_TOTAL = NET_TOTAL + TAX_AMOUNT + SHIPPING_AMOUNT  # 3120
TAX_DESCRIPTION = "Sales Tax 10%"
SHIPPING_DESCRIPTION = "Shipping Charge"


class TestCartConversion(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.suffix = uuid.uuid4().hex[:8]
		self.make_masters()
		self.quotation = self.make_quotation()

	def make_masters(self) -> None:
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "__newname": "Transit"}).insert(
				ignore_permissions=True
			)
		self.company_doc = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": f"Ceto Proof Co {self.suffix}",
				"abbr": f"CP{self.suffix[:4]}".upper(),
				"country": "United States",
				"default_currency": "USD",
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert(ignore_permissions=True)
		self.company = self.company_doc.name
		self.abbr = self.company_doc.abbr
		self.cost_center = self.company_doc.cost_center

		year = date.today().year
		fiscal_year = f"{year} ({self.company})"
		if not frappe.db.exists("Fiscal Year", fiscal_year):
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": fiscal_year,
					"year_start_date": f"{year}-01-01",
					"year_end_date": f"{year}-12-31",
					"companies": [{"company": self.company}],
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Territory", "All Territories"):
			frappe.get_doc(
				{"doctype": "Territory", "territory_name": "All Territories", "is_group": 1}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Group", "All Item Groups"):
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("UOM", "Nos"):
			frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)

		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		if not customer_group:
			customer_group = (
				frappe.get_doc(
					{"doctype": "Customer Group", "customer_group_name": f"Individual {self.suffix}"}
				)
				.insert(ignore_permissions=True)
				.name
			)

		# Guest Customer of the shopping cart
		self.customer = (
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

		self.price_list = f"Selling {self.suffix}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": self.price_list,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
				"currency": "USD",
			}
		).insert(ignore_permissions=True)

		self.item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"CETO-PROOF-ITEM-{self.suffix}",
					"item_name": f"Ceto Proof Item {self.suffix}",
					"item_group": "All Item Groups",
					"stock_uom": "Nos",
					"is_stock_item": 0,
					"is_sales_item": 1,
					"item_defaults": [
						{
							"company": self.company,
							"income_account": f"Sales - {self.abbr}",
							"expense_account": f"Cost of Goods Sold - {self.abbr}",
							"selling_cost_center": self.cost_center,
							"buying_cost_center": self.cost_center,
						}
					],
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		# the single item price driving the cart line
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.item,
				"price_list": self.price_list,
				"price_list_rate": RATE,
				"currency": "USD",
			}
		).insert(ignore_permissions=True)

	def make_quotation(self):
		quote = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": self.customer,
				"order_type": "Shopping Cart",
				"company": self.company,
				"currency": "USD",
				"conversion_rate": 1,
				"selling_price_list": self.price_list,
				"transaction_date": today(),
				"valid_till": date.today() + timedelta(days=30),
				# coupon-equivalent: a real additional discount on Net Total
				"apply_discount_on": "Net Total",
				"additional_discount_percentage": DISCOUNT_PERCENTAGE,
				"items": [{"item_code": self.item, "qty": QTY}],
			}
		).insert(ignore_permissions=True)

		# real tax row and real shipping charge row (shipping identified by
		# its description); ERPNext recalculates all amounts itself
		quote.append(
			"taxes",
			{
				"charge_type": "On Net Total",
				"account_head": f"Duties and Taxes - {self.abbr}",
				"rate": TAX_PERCENTAGE,
				"description": TAX_DESCRIPTION,
				"cost_center": self.cost_center,
			},
		)
		quote.append(
			"taxes",
			{
				"charge_type": "Actual",
				"account_head": f"Sales - {self.abbr}",
				"tax_amount": SHIPPING_AMOUNT,
				"description": SHIPPING_DESCRIPTION,
				"cost_center": self.cost_center,
			},
		)
		return quote.save(ignore_permissions=True)

	def test_quotation_to_sales_order_proof(self) -> None:
		with self.subTest(stage="draft quotation priced from item price"):
			quote = self.quotation
			self.assertEqual(quote.docstatus, 0)
			self.assertEqual(quote.order_type, "Shopping Cart")
			self.assertEqual(quote.party_name, self.customer)
			self.assertEqual(len(quote.items), 1)
			row = quote.items[0]
			self.assertEqual(row.item_code, self.item)
			self.assertEqual(row.qty, QTY)
			self.assertAlmostEqual(flt(row.price_list_rate), RATE)
			self.assertAlmostEqual(flt(row.rate), RATE)
			self.assertAlmostEqual(flt(quote.discount_amount), DISCOUNT_AMOUNT)
			self.assertAlmostEqual(flt(quote.net_total), NET_TOTAL)

		with self.subTest(stage="tax and shipping charge rows"):
			quote = self.quotation.reload()
			tax_row = quote.get("taxes", {"description": TAX_DESCRIPTION})
			ship_row = quote.get("taxes", {"description": SHIPPING_DESCRIPTION})
			self.assertEqual(len(tax_row), 1)
			self.assertEqual(len(ship_row), 1)
			self.assertAlmostEqual(flt(tax_row[0].tax_amount), TAX_AMOUNT)
			self.assertAlmostEqual(flt(ship_row[0].tax_amount), SHIPPING_AMOUNT)
			self.assertAlmostEqual(flt(quote.total_taxes_and_charges), TAX_AMOUNT + SHIPPING_AMOUNT)
			self.assertAlmostEqual(flt(quote.grand_total), GRAND_TOTAL)

		with self.subTest(stage="submit quotation"):
			self.quotation.submit()
			self.assertEqual(self.quotation.docstatus, 1)

		with self.subTest(stage="convert to submitted sales order"):
			sales_order = convert_quotation_to_sales_order(self.quotation.name, submit=True)
			self.assertEqual(sales_order.docstatus, 1)
			self.assertEqual(sales_order.customer, self.customer)
			self.assertEqual(sales_order.order_type, "Shopping Cart")
			self.assertEqual(len(sales_order.items), 1)
			so_row = sales_order.items[0]
			self.assertEqual(so_row.item_code, self.item)
			self.assertEqual(so_row.qty, QTY)
			self.assertAlmostEqual(flt(so_row.rate), RATE)
			# coupon-equivalent discount survives the mapper
			self.assertAlmostEqual(flt(sales_order.discount_amount), DISCOUNT_AMOUNT)
			self.assertAlmostEqual(flt(sales_order.net_total), NET_TOTAL)
			# tax and shipping rows survive the mapper
			so_tax = sales_order.get("taxes", {"description": TAX_DESCRIPTION})
			so_ship = sales_order.get("taxes", {"description": SHIPPING_DESCRIPTION})
			self.assertEqual(len(so_tax), 1)
			self.assertEqual(len(so_ship), 1)
			self.assertAlmostEqual(flt(so_tax[0].tax_amount), TAX_AMOUNT)
			self.assertAlmostEqual(flt(so_ship[0].tax_amount), SHIPPING_AMOUNT)
			self.assertAlmostEqual(flt(sales_order.grand_total), GRAND_TOTAL)
			# per-item quotation linkage preserved
			self.assertEqual(so_row.prevdoc_docname, self.quotation.name)
			self.assertEqual(frappe.db.get_value("Quotation", self.quotation.name, "status"), "Ordered")


if __name__ == "__main__":
	unittest.main()
