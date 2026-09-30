"""Guarantee the UOMs referenced by the development catalog."""

import frappe

from ceto.data.base_importer import BaseImporter, Report, values_differ
from ceto.data.bootstrap_dev.dataset import UOMS, UomSeed
from ceto.data.bootstrap_dev.settings import BootstrapSettings


class SetupUoms(BaseImporter):
	"""Create missing UOMs and leave shared ERPNext UOM masters untouched.

	An existing UOM is reported as skipped. When its whole-number flag differs
	from the catalog expectation, a note records the difference instead of
	mutating a master that other documents may depend on.
	"""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		for seed in UOMS:
			self.make_uom(seed)
		return self.report

	def make_uom(self, seed: UomSeed) -> None:
		if frappe.db.exists("UOM", seed.uom_name):
			current = frappe.db.get_value("UOM", seed.uom_name, "must_be_whole_number")
			if values_differ(current, seed.must_be_whole_number):
				self.record_note(
					f"UOM {seed.uom_name} exists with must_be_whole_number={current}; left unchanged."
				)
			self.record_change("skipped", "UOM", seed.uom_name)
			return

		doc = frappe.new_doc("UOM")
		doc.uom_name = seed.uom_name
		self.create_and_record(doc, {"must_be_whole_number": seed.must_be_whole_number}, "UOM", seed.uom_name)


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the UOM seeder."""
	return SetupUoms(settings or BootstrapSettings()).make()
