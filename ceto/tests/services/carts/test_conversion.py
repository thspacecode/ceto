"""Integration proof: Shopping Cart Quotation -> Sales Order via ERPNext mapper.

Runs against real ERPNext behaviour on ``default.site`` inside a single
rolled-back transaction (no mocks of calculations or core):

* the committed bootstrap_dev commerce masters (Company, guest Customer,
  selling Price List, Item + Item Price), imported once through
  ``ceto.tests.utils``,
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

from datetime import date, timedelta

import frappe
from frappe.utils import flt, today

from ceto.data.bootstrap_dev.dataset import ITEM_PRICES
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.tests.utils import CetoTestSuite, boot_strap_test_master_data

ITEM_CODE = "DEV-TSHIRT-001"
RATE = float(next(seed.price_list_rate for seed in ITEM_PRICES if seed.item_code == ITEM_CODE))
QTY = 3
DISCOUNT_PERCENTAGE = 10.0
TAX_PERCENTAGE = 10.0
SHIPPING_AMOUNT = 150.0
GROSS = RATE * QTY  # 75
DISCOUNT_AMOUNT = GROSS * DISCOUNT_PERCENTAGE / 100  # 7.5
NET_TOTAL = GROSS - DISCOUNT_AMOUNT  # 67.5
TAX_AMOUNT = NET_TOTAL * TAX_PERCENTAGE / 100  # 6.75
GRAND_TOTAL = NET_TOTAL + TAX_AMOUNT + SHIPPING_AMOUNT  # 224.25
TAX_DESCRIPTION = "Sales Tax 10%"
SHIPPING_DESCRIPTION = "Shipping Charge"


class TestCartConversion(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		# commerce masters come from the committed bootstrap_dev baseline that
		# ceto.tests.utils created once at import; only the transaction-scoped
		# records are (re)created per test.
		settings = boot_strap_test_master_data.resolve_baseline_settings()
		self.company = resolve_company(settings)
		self.company_doc = frappe.get_doc("Company", self.company)
		self.abbr = self.company_doc.abbr
		self.cost_center = self.company_doc.cost_center
		# Guest Customer of the shopping cart, located like the bootstrap does:
		# by customer_name, never by docname.
		self.customer = frappe.db.get_value("Customer", {"customer_name": settings.guest_customer_name})
		self.price_list = settings.selling_price_list
		self.item = ITEM_CODE
		if not frappe.db.exists("Warehouse Type", "Transit"):
			frappe.get_doc({"doctype": "Warehouse Type", "__newname": "Transit"}).insert(
				ignore_permissions=True
			)
		self.quotation = self.make_quotation()

	def make_quotation(self):
		quote = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": self.customer,
				"order_type": "Shopping Cart",
				"company": self.company,
				"currency": self.company_doc.default_currency,
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
