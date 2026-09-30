"""Seed the development item catalog."""

import frappe

from ceto.data.base_importer import BaseImporter, Report, apply_values
from ceto.data.bootstrap_dev.dataset import ITEMS, ItemSeed
from ceto.data.bootstrap_dev.seeders.setup_company import resolve_company
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import AmbiguousIdentityError, BootstrapError


class SetupItems(BaseImporter):
	"""Seed Dev items with their company-scoped Item Defaults row.

	Items are stock-enabled masters only: no stock ledger entries, bins, or
	opening quantities are created here.
	"""

	def __init__(self, settings: BootstrapSettings, company: str) -> None:
		super().__init__()
		self.settings = settings
		self.company = company

	def make(self) -> Report:
		for seed in ITEMS:
			self.make_item(seed)
		return self.report

	def make_item(self, seed: ItemSeed) -> None:
		owned = {
			"item_name": seed.item_name,
			"item_group": seed.item_group,
			"stock_uom": seed.stock_uom,
			"description": seed.description,
			"is_stock_item": seed.is_stock_item,
			"is_sales_item": seed.is_sales_item,
			"is_purchase_item": seed.is_purchase_item,
		}
		if frappe.db.exists("Item", seed.item_code):
			doc = frappe.get_doc("Item", seed.item_code)
			changed = apply_values(doc, owned)
			changed = self.apply_item_defaults(doc, seed) or changed
			if changed:
				doc.save()
				self.record_change("updated", "Item", seed.item_code)
			else:
				self.record_change("skipped", "Item", seed.item_code)
		else:
			doc = frappe.new_doc("Item")
			doc.item_code = seed.item_code
			doc.update(owned)
			self.apply_item_defaults(doc, seed)
			doc.insert()
			self.record_change("created", "Item", seed.item_code)

	def apply_item_defaults(self, doc, seed: ItemSeed) -> bool:
		"""Point the item's defaults row for the bootstrap company at Dev records."""
		rows = [row for row in doc.item_defaults if row.company == self.company]
		if len(rows) > 1:
			msg = (
				f"Item {seed.item_code} has {len(rows)} Item Defaults rows for "
				f"{self.company}; resolve the duplicate before rerunning."
			)
			raise AmbiguousIdentityError(msg)

		expected = {
			"default_warehouse": self.resolve_warehouse_docname(seed),
			"default_price_list": self.settings.selling_price_list,
		}
		if not rows:
			doc.append("item_defaults", {"company": self.company, **expected})
			return True
		return apply_values(rows[0], expected)

	def resolve_warehouse_docname(self, seed: ItemSeed) -> str:
		if not seed.default_warehouse:
			return ""
		filters = {"warehouse_name": seed.default_warehouse, "company": self.company}
		label = f"default warehouse '{seed.default_warehouse}' for item {seed.item_code}"
		name = self.resolve_unique_name("Warehouse", filters, label)
		if not name:
			msg = f"Warehouse '{seed.default_warehouse}' required by item {seed.item_code} not found."
			frappe.throw(msg, BootstrapError)
		return name


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the item seeder."""
	resolved = settings or BootstrapSettings()
	return SetupItems(resolved, resolve_company(resolved)).make()
