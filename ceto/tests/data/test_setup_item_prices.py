"""DB-backed regression tests for Item Price bootstrap convergence."""

from dataclasses import replace
from decimal import Decimal
from unittest.mock import patch

import frappe

from ceto.data.bootstrap_dev.dataset import ItemPriceSeed
from ceto.data.bootstrap_dev.seeders.setup_item_prices import SetupItemPrices
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.utils import CetoTestSuite


class TestSetupItemPrices(CetoTestSuite):
	def test_created_rate_is_found_and_skipped_on_rerun(self):
		if not frappe.db.exists("DocType", "Item Price"):
			self.skipTest("ERPNext Item Price is not installed")

		uom = frappe.db.get_value("UOM", {}, "name")
		if not frappe.db.exists("Item Group", "All Item Groups") or not uom:
			self.skipTest("ERPNext Item Group root and UOM prerequisites are unavailable")

		suffix = frappe.generate_hash(length=8).upper()
		item_group = f"Dev Price Test {suffix}"
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": item_group,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert()
		item_code = f"DEV-PRICE-{suffix}"
		price_list = f"Ceto Dev Price {suffix}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": price_list,
				"currency": "USD",
				"enabled": 1,
				"selling": 1,
			}
		).insert()
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": item_group,
				"stock_uom": uom,
				"is_stock_item": 0,
				"is_sales_item": 1,
			}
		).insert()

		settings = replace(
			BootstrapSettings(), selling_price_list=price_list, item_price_valid_from="2000-01-01"
		)
		seed = ItemPriceSeed(item_code=item_code, price_list_rate=Decimal("19.95"))
		label = f"Dev selling rate for {item_code} on {price_list}"

		with patch("ceto.data.bootstrap_dev.seeders.setup_item_prices.ITEM_PRICES", (seed,)):
			first = SetupItemPrices(settings, "unused company").make()
			second = SetupItemPrices(settings, "unused company").make()

		self.assertEqual(first["created"], {"Item Price": [label]})
		self.assertEqual(second["skipped"], {"Item Price": [label]})
		self.assertEqual(frappe.db.count("Item Price", {"price_list": price_list, "item_code": item_code}), 1)
		row = frappe.db.get_value(
			"Item Price",
			{"price_list": price_list, "item_code": item_code},
			["valid_from", "valid_upto", "customer", "supplier", "batch_no", "packing_unit"],
			as_dict=True,
		)
		self.assertEqual(str(row.valid_from), "2000-01-01")
		self.assertFalse(row.valid_upto)
		self.assertFalse(row.customer)
		self.assertFalse(row.supplier)
		self.assertFalse(row.batch_no)
		self.assertFalse(row.packing_unit)
