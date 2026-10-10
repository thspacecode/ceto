"""DB-backed regression tests for the Ceto catalog bootstrap convergence.

``SetupCatalog`` seeds the demo collections and product types Ceto stores
itself, located by their stable business keys (collection ``handle``, type
``value``) with the public ids minted once at creation. The tests pin that a
fresh run creates those records, a rerun converges to all-skipped, a drifted
served field is rewritten, and the minted ids survive every rerun untouched.
An ambiguous business key is structurally impossible behind the storage's
unique indexes, so the seeder has no resolution beyond the importer's
ambiguity guard.
"""

import json

import frappe

from ceto.data.bootstrap_dev.dataset import COLLECTIONS, PRODUCT_TYPES
from ceto.data.bootstrap_dev.seeders.setup_catalog import SetupCatalog
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.utils import CetoTestSuite


class TestSetupCatalog(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.delete("Ceto Collection", {"handle": ["in", [seed.handle for seed in COLLECTIONS]]})
		frappe.db.delete("Ceto Product Type", {"value": ["in", [seed.value for seed in PRODUCT_TYPES]]})

	def seed(self) -> dict:
		return SetupCatalog(BootstrapSettings()).make()

	def test_creates_the_demo_catalog_with_minted_ids(self):
		report = self.seed()

		self.assertEqual(report["created"].get("Ceto Collection"), [seed.handle for seed in COLLECTIONS])
		self.assertEqual(report["created"].get("Ceto Product Type"), [seed.value for seed in PRODUCT_TYPES])

		primary = frappe.get_doc("Ceto Collection", {"handle": COLLECTIONS[0].handle})
		self.assertTrue(primary.collection_id.startswith("pcol_"))
		self.assertEqual(primary.title, COLLECTIONS[0].title)
		self.assertEqual(json.loads(primary.metadata), COLLECTIONS[0].metadata)

		typed = frappe.get_doc("Ceto Product Type", {"value": PRODUCT_TYPES[0].value})
		self.assertTrue(typed.type_id.startswith("ptyp_"))
		self.assertEqual(typed.external_id, PRODUCT_TYPES[0].external_id)

	def test_rerun_converges_to_all_skipped_and_keeps_the_minted_ids(self):
		self.seed()
		ids_before = frappe.get_all("Ceto Collection", pluck="collection_id")

		report = self.seed()

		self.assertEqual(report["created"], {})
		self.assertEqual(report["updated"], {})
		self.assertEqual(
			sorted(report["skipped"].get("Ceto Collection", [])),
			sorted(seed.handle for seed in COLLECTIONS),
		)
		self.assertEqual(
			sorted(report["skipped"].get("Ceto Product Type", [])),
			sorted(seed.value for seed in PRODUCT_TYPES),
		)
		# The public ids are minted once at creation and never rewritten.
		self.assertEqual(frappe.get_all("Ceto Collection", pluck="collection_id"), ids_before)

	def test_drifted_served_fields_are_rewritten(self):
		self.seed()
		handle = COLLECTIONS[0].handle
		frappe.db.set_value("Ceto Collection", {"handle": handle}, "title", "Drifted Title")

		report = self.seed()

		self.assertEqual(report["updated"].get("Ceto Collection"), [handle])
		self.assertEqual(
			frappe.db.get_value("Ceto Collection", {"handle": handle}, "title"),
			COLLECTIONS[0].title,
		)
