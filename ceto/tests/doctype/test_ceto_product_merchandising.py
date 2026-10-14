"""Ceto Product Merchandising storage: one record per Item, validated links.

Runs real inserts on the test site inside a single rolled-back transaction:
the record is named by the exact ERPNext Item code — one record per Item,
the uniqueness the served singular collection / type semantics need — both
links are optional but an empty assignment is refused, unknown masters are
refused by the Link validation, and deleting a collection or a product type
detaches its references while a record that keeps its other link survives.
The Item reference itself stays a stable, blocking one: an Item cannot be
deleted while its merchandising record exists.
"""

import frappe

from ceto.tests.data.catalog_test_data import CatalogTestData
from ceto.tests.utils import CetoTestSuite


class TestCetoProductMerchandising(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.fixtures = CatalogTestData()
		self.collection = self.fixtures.collection()
		self.product_type = self.fixtures.product_type()
		self.item = self.fixtures.item()

	def make_merchandising(self, item: str | None = None, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Product Merchandising",
				"item": item or self.item.name,
				"collection": self.collection.name,
				"product_type": self.product_type.name,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_the_record_by_the_exact_item_code(self) -> None:
		merchandising = self.make_merchandising()

		loaded = frappe.get_doc("Ceto Product Merchandising", self.item.name)
		self.assertEqual(loaded.name, self.item.name)
		self.assertEqual(loaded.item, self.item.name)
		self.assertEqual(loaded.collection, self.collection.name)
		self.assertEqual(loaded.product_type, self.product_type.name)
		self.assertEqual(merchandising.name, self.item.name)

	def test_one_record_per_item(self) -> None:
		self.make_merchandising()

		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self.make_merchandising()

	def test_requires_at_least_one_link(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self.make_merchandising(collection=None, product_type=None)

	def test_the_links_are_optional_individually(self) -> None:
		collection_only = self.make_merchandising(product_type=None)
		self.assertIsNone(collection_only.product_type)

		type_only = self.make_merchandising(item=self.fixtures.item().name, collection=None)
		self.assertIsNone(type_only.collection)

	def test_unknown_references_are_refused(self) -> None:
		for overrides in ({"collection": "missing-collection"}, {"product_type": "missing-type"}):
			with self.subTest(overrides=overrides):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self.make_merchandising(**overrides)

	def test_deleting_the_collection_detaches_its_records(self) -> None:
		both = self.make_merchandising()
		type_only = self.make_merchandising(item=self.fixtures.item().name, collection=None)

		frappe.delete_doc("Ceto Collection", self.collection.name, ignore_permissions=True)

		detached = frappe.get_doc("Ceto Product Merchandising", both.name)
		self.assertIsNone(detached.collection)
		self.assertEqual(detached.product_type, self.product_type.name)
		self.assertTrue(frappe.db.exists("Ceto Product Merchandising", type_only.name))

	def test_deleting_the_last_link_deletes_the_record(self) -> None:
		collection_only = self.make_merchandising(product_type=None)

		frappe.delete_doc("Ceto Collection", self.collection.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("Ceto Product Merchandising", collection_only.name))

	def test_deleting_the_product_type_detaches_symmetrically(self) -> None:
		both = self.make_merchandising()
		collection_only = self.make_merchandising(item=self.fixtures.item().name, product_type=None)

		frappe.delete_doc("Ceto Product Type", self.product_type.name, ignore_permissions=True)

		detached = frappe.get_doc("Ceto Product Merchandising", both.name)
		self.assertEqual(detached.collection, self.collection.name)
		self.assertIsNone(detached.product_type)
		self.assertTrue(frappe.db.exists("Ceto Product Merchandising", collection_only.name))

	def test_deleting_the_item_stays_blocked_while_the_record_exists(self) -> None:
		self.make_merchandising()

		with self.assertRaises(frappe.LinkExistsError):
			frappe.delete_doc("Item", self.item.name, ignore_permissions=True)
