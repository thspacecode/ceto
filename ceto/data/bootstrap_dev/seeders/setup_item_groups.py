"""Seed the development Item Group tree used as storefront categories."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.dataset import ITEM_GROUPS, ItemGroupSeed
from ceto.data.bootstrap_dev.settings import BootstrapSettings

ROOT_ITEM_GROUP = "All Item Groups"


class SetupItemGroups(BaseImporter):
	"""Seed the Dev category tree under the site root item group."""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		for seed in ITEM_GROUPS:
			self.make_item_group(seed)
		return self.report

	def make_item_group(self, seed: ItemGroupSeed) -> None:
		owned = {
			"parent_item_group": seed.parent or ROOT_ITEM_GROUP,
			"is_group": seed.is_group,
		}
		if frappe.db.exists("Item Group", seed.item_group_name):
			doc = frappe.get_doc("Item Group", seed.item_group_name)
			self.update_and_record(doc, owned, "Item Group", seed.item_group_name)
		else:
			doc = frappe.new_doc("Item Group")
			doc.item_group_name = seed.item_group_name
			self.create_and_record(doc, owned, "Item Group", seed.item_group_name)


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the item group seeder."""
	return SetupItemGroups(settings or BootstrapSettings()).make()
