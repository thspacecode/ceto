"""Seed the demo collections and product types Ceto stores itself."""

import frappe

from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.dataset import COLLECTIONS, PRODUCT_TYPES, CollectionSeed, ProductTypeSeed
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.services.catalog.collections import new_collection_id
from ceto.services.catalog.product_types import new_product_type_id
from ceto.services.common import dump_metadata


class SetupCatalog(BaseImporter):
	"""Seed the demo collections and product types owned by the Ceto catalog.

	Collections are located by their unique ``handle`` and product types by
	their unique ``value`` — each record's stable business key — while the
	public ``pcol_…`` / ``ptyp_…`` ids are minted once at creation and never
	rewritten. Reruns converge the served fields only.
	"""

	def __init__(self, settings: BootstrapSettings) -> None:
		super().__init__()
		self.settings = settings

	def make(self) -> Report:
		for seed in COLLECTIONS:
			self.make_collection(seed)
		for seed in PRODUCT_TYPES:
			self.make_product_type(seed)
		return self.report

	def make_collection(self, seed: CollectionSeed) -> None:
		owned = {
			"handle": seed.handle,
			"title": seed.title,
			"external_id": seed.external_id,
			"metadata": dump_metadata(seed.metadata),
		}
		name = self.resolve_unique_name("Ceto Collection", {"handle": seed.handle}, f"handle {seed.handle!r}")
		if name:
			doc = frappe.get_doc("Ceto Collection", name)
			self.update_and_record(doc, owned, "Ceto Collection", seed.handle)
		else:
			doc = frappe.new_doc("Ceto Collection")
			doc.collection_id = new_collection_id()
			self.create_and_record(doc, owned, "Ceto Collection", seed.handle)

	def make_product_type(self, seed: ProductTypeSeed) -> None:
		owned = {
			"value": seed.value,
			"external_id": seed.external_id,
			"metadata": dump_metadata(seed.metadata),
		}
		name = self.resolve_unique_name("Ceto Product Type", {"value": seed.value}, f"value {seed.value!r}")
		if name:
			doc = frappe.get_doc("Ceto Product Type", name)
			self.update_and_record(doc, owned, "Ceto Product Type", seed.value)
		else:
			doc = frappe.new_doc("Ceto Product Type")
			doc.type_id = new_product_type_id()
			self.create_and_record(doc, owned, "Ceto Product Type", seed.value)


def execute(settings: BootstrapSettings | None = None) -> Report:
	"""Run only the catalog seeder."""
	return SetupCatalog(settings or BootstrapSettings()).make()
