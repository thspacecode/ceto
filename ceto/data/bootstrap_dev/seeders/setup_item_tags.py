"""Seed the demo item tags the Store tag projection serves."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.dataset import ITEM_TAGS, ItemTagSeed
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import BootstrapError
from ceto.services.catalog.product_tags import (
	add_item_tag,
	ensure_tag_master,
	item_tag_exists,
)


class SetupItemTags(BaseImporter):
	"""Pin deterministic demo tags on the Dev items.

	Each tag is located by its master name — the ``Tag`` doctype's own
	business key — and by the exact live ``Tag Link`` row naming the item, so
	a rerun converges to all-skipped and a removed tag is re-applied. The
	public tag ids are derived from the value at read time; nothing is
	minted or stored.
	"""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		for value in sorted({value for seed in ITEM_TAGS for value in seed.tags}):
			self.make_tag_master(value)
		for seed in ITEM_TAGS:
			self.make_item_tags(seed)
		return self.report

	def make_tag_master(self, value: str) -> None:
		change = "created" if not frappe.db.exists("Tag", value) else "skipped"
		ensure_tag_master(value)
		self.record_change(change, "Tag", value)

	def make_item_tags(self, seed: ItemTagSeed) -> None:
		if not frappe.db.exists("Item", seed.item_code):
			msg = f"Item {seed.item_code} not found; run the item seeder first."
			frappe.throw(msg, BootstrapError)
		for value in seed.tags:
			self.make_item_tag(seed.item_code, value)

	def make_item_tag(self, item_code: str, value: str) -> None:
		label = f"tag {value!r} on {item_code}"
		if item_tag_exists(item_code, value):
			self.record_change("skipped", "Tag Link", label)
			return
		add_item_tag(item_code, value)
		self.record_change("created", "Tag Link", label)


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the item tag seeder."""
	return SetupItemTags(settings or BootstrapSettings()).make()
