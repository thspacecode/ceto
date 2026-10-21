"""DB-backed regression tests for the Ceto item tag bootstrap convergence.

``SetupItemTags`` pins the deterministic demo tags on the Dev items, located
by the ``Tag`` master name and the exact live ``Tag Link`` row naming the
item. The tests pin that a fresh run creates the masters and the links, a
rerun converges to all-skipped, a removed tag is re-applied, and the missing
item prerequisite aborts loudly.
"""

import frappe

from ceto.data.bootstrap_dev.dataset import ITEM_TAGS
from ceto.data.bootstrap_dev.seeders.setup_item_tags import SetupItemTags
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.exceptions import BootstrapError
from ceto.tests.utils import CetoTestSuite


class TestSetupItemTags(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		values = [value for seed in ITEM_TAGS for value in seed.tags]
		frappe.db.delete("Tag Link", {"document_type": "Item", "tag": ["in", values]})
		frappe.db.delete("Tag", {"name": ["in", values]})

	def seed(self) -> dict:
		return SetupItemTags(BootstrapSettings()).make()

	def item_codes(self) -> set[str]:
		return {seed.item_code for seed in ITEM_TAGS}

	def tag_values(self) -> set[str]:
		return {value for seed in ITEM_TAGS for value in seed.tags}

	def test_creates_the_demo_tag_masters_and_the_item_links(self):
		report = self.seed()

		self.assertEqual(sorted(report["created"].get("Tag", [])), sorted(self.tag_values()))
		self.assertEqual(len(report["created"].get("Tag Link", [])), self.link_count())
		for item_code in self.item_codes():
			with self.subTest(item_code=item_code):
				for value in self.item_tags(item_code):
					self.assertTrue(
						frappe.db.exists(
							"Tag Link",
							{"document_type": "Item", "document_name": item_code, "tag": value},
						)
					)

	def link_count(self) -> int:
		return sum(len(seed.tags) for seed in ITEM_TAGS)

	def item_tags(self, item_code: str) -> list[str]:
		return next(seed.tags for seed in ITEM_TAGS if seed.item_code == item_code)

	def test_rerun_converges_to_all_skipped(self):
		self.seed()

		report = self.seed()

		self.assertEqual(report["created"], {})
		self.assertEqual(report["updated"], {})
		self.assertEqual(sorted(report["skipped"].get("Tag", [])), sorted(self.tag_values()))
		self.assertEqual(len(report["skipped"].get("Tag Link", [])), self.link_count())

	def test_a_removed_tag_is_reapplied(self):
		self.seed()
		item_code = ITEM_TAGS[0].item_code
		value = ITEM_TAGS[0].tags[0]
		frappe.db.delete("Tag Link", {"document_type": "Item", "document_name": item_code, "tag": value})

		report = self.seed()

		self.assertEqual(report["created"].get("Tag Link"), [f"tag {value!r} on {item_code}"])
		self.assertTrue(
			frappe.db.exists("Tag Link", {"document_type": "Item", "document_name": item_code, "tag": value})
		)

	def test_a_missing_item_prerequisite_aborts_loudly(self):
		frappe.db.delete("Tag Link", {"document_type": "Item"})
		frappe.db.delete("Tag", {"name": ["in", list(self.tag_values())]})
		first = ITEM_TAGS[0].item_code
		frappe.db.delete("Item", first)

		with self.assertRaises(BootstrapError):
			self.seed()
