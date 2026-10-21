"""DB-backed regression tests for the Item Group bootstrap convergence.

``SetupItemGroups`` seeds the demo ``Dev *`` category tree — the fixture the
category behavior slice serves (Recorded Decision 7) — located by its stable
business key (the Item Group name), owning only ``parent_item_group`` and
``is_group``. The tests pin that a missing demo node is created in place, a
rerun converges to all-skipped, and a drifted owned field is rewritten. The
pre-existing ERPNext default groups are never touched: the seeder writes
only the dataset's own rows.
"""

import frappe

from ceto.data.bootstrap_dev.dataset import ITEM_GROUPS
from ceto.data.bootstrap_dev.seeders.setup_item_groups import ROOT_ITEM_GROUP, SetupItemGroups
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.utils import CetoTestSuite

OVERLAY = "Dev Graphic Tees"


class TestSetupItemGroups(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		frappe.db.delete("Item Group", {"item_group_name": OVERLAY})

	def seed(self) -> dict:
		return SetupItemGroups(BootstrapSettings()).make()

	def test_creates_missing_demo_nodes_in_place(self):
		report = self.seed()

		self.assertEqual(report["created"].get("Item Group"), [OVERLAY])
		node = frappe.get_doc("Item Group", OVERLAY)
		self.assertEqual(node.parent_item_group, "Dev T-Shirts")
		self.assertFalse(node.is_group)

	def test_rerun_converges_to_all_skipped(self):
		self.seed()

		report = self.seed()

		self.assertEqual(report["created"], {})
		self.assertEqual(report["updated"], {})
		self.assertEqual(
			sorted(report["skipped"].get("Item Group", [])),
			sorted(seed.item_group_name for seed in ITEM_GROUPS),
		)

	def test_drifted_owned_fields_are_rewritten(self):
		self.seed()
		frappe.db.set_value("Item Group", OVERLAY, "is_group", 1)

		report = self.seed()

		self.assertEqual(report["updated"].get("Item Group"), [OVERLAY])
		self.assertFalse(frappe.db.get_value("Item Group", OVERLAY, "is_group"))

	def test_the_demo_tree_hangs_off_the_site_root(self):
		self.seed()

		top_level = [
			seed.item_group_name
			for seed in ITEM_GROUPS
			if frappe.db.get_value("Item Group", seed.item_group_name, "parent_item_group") == ROOT_ITEM_GROUP
		]

		self.assertIn("Dev Apparel", top_level)
		self.assertIn("Dev Clearance", top_level)
