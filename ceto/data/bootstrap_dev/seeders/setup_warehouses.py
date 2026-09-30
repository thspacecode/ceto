"""Seed the development warehouse hierarchy under the company root warehouse."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.dataset import WAREHOUSES, WarehouseSeed
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import BootstrapError


class SetupWarehouses(BaseImporter):
	"""Seed the Dev warehouse tree; parents are always created before children."""

	def __init__(self, settings: BootstrapSettings, company: str) -> None:
		super().__init__()
		self.settings = settings
		self.company = company

	def make(self) -> Report:
		for seed in WAREHOUSES:
			self.make_warehouse(seed)
		return self.report

	def make_warehouse(self, seed: WarehouseSeed) -> None:
		filters = {"warehouse_name": seed.warehouse_name, "company": self.company}
		label = f"Warehouse '{seed.warehouse_name}' in {self.company}"
		name = self.resolve_unique_name("Warehouse", filters, label)

		owned = {
			"parent_warehouse": self.resolve_parent_docname(seed),
			"is_group": seed.is_group,
		}
		if name:
			doc = frappe.get_doc("Warehouse", name)
			self.update_and_record(doc, owned, "Warehouse", name)
		else:
			doc = frappe.new_doc("Warehouse")
			doc.warehouse_name = seed.warehouse_name
			doc.company = self.company
			self.create_and_record(doc, owned, "Warehouse", seed.warehouse_name)

	def resolve_parent_docname(self, seed: WarehouseSeed) -> str:
		if seed.parent is None:
			filters = {"company": self.company, "is_group": 1, "parent_warehouse": ("is", "not set")}
			label = f"root warehouse for {self.company}"
			parent = self.resolve_unique_name("Warehouse", filters, label)
			if not parent:
				msg = f"Company {self.company} has no root warehouse."
				frappe.throw(msg, BootstrapError)
			return parent

		filters = {"warehouse_name": seed.parent, "company": self.company}
		label = f"parent warehouse '{seed.parent}' in {self.company}"
		parent = self.resolve_unique_name("Warehouse", filters, label)
		if not parent:
			msg = f"Parent warehouse '{seed.parent}' for {seed.warehouse_name} not found."
			frappe.throw(msg, BootstrapError)
		return parent
