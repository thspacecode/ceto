"""Phase 2 compatibility record: Ceto Cart Line Item Reference persistence.

Runs against real ERPNext behaviour on the test site inside a single rolled-back
transaction: a guest cart Quotation created via ``CartService`` receives a
Quotation Item row, and the standalone mapping doctype is validated, uniquely
named by ``line_id`` and explicitly cleaned up when the cart reference dies.
"""

import uuid

import frappe

from ceto.services.carts.quotation import CartService
from ceto.services.carts.variants import resolve_item_code
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoCartLineItemReference(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.suffix = uuid.uuid4().hex[:8]
		self.masters = CartTestData()
		self.item = self._make_item()
		self.reference, self.quotation = self._make_cart()

	def _make_item(self) -> str:
		return self.masters.item

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _append_quotation_item(self) -> str:
		self.quotation.append("items", {"item_code": self.item, "qty": 2})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)
		return self.quotation.items[-1].name

	def _make_line_reference(self, quotation_item: str, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Cart Line Item Reference",
				"line_id": f"li_{uuid.uuid4().hex}",
				"cart_reference": self.reference.name,
				"quotation": self.quotation.name,
				"quotation_item": quotation_item,
				"metadata": '{"source": "test"}',
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_maps_line_id_to_quotation_item_row(self) -> None:
		row = self._append_quotation_item()
		reference = self._make_line_reference(row)

		loaded = frappe.get_doc("Ceto Cart Line Item Reference", reference.name)
		self.assertEqual(loaded.name, reference.line_id)
		self.assertEqual(loaded.cart_reference, self.reference.name)
		self.assertEqual(loaded.quotation, self.quotation.name)
		self.assertEqual(loaded.quotation_item, row)
		self.assertEqual(loaded.metadata, '{"source": "test"}')

	def test_line_id_is_unique(self) -> None:
		row = self._append_quotation_item()
		line_id = f"li_{uuid.uuid4().hex}"
		self._make_line_reference(row, line_id=line_id)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_line_reference(row, line_id=line_id)

	def test_rejects_row_from_another_quotation(self) -> None:
		row = self._append_quotation_item()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_line_reference(row, quotation=self.quotation.name + "X")

	def test_rejects_mismatched_cart_reference(self) -> None:
		row = self._append_quotation_item()
		other_reference, _other_quotation = self._make_cart()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_line_reference(row, cart_reference=other_reference.name)

	def test_rejects_unknown_quotation_item_row(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_line_reference("not-a-row")

	def test_rejects_non_object_metadata(self) -> None:
		row = self._append_quotation_item()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_line_reference(row, metadata="[1, 2]")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_line_reference(row, metadata="not json")

	def test_cart_reference_delete_cleans_up_line_references(self) -> None:
		row = self._append_quotation_item()
		line = self._make_line_reference(row)

		frappe.delete_doc("Ceto Cart Reference", self.reference.name, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Ceto Cart Line Item Reference", line.name))

	def test_variant_resolution_uses_item_code_identity(self) -> None:
		from ceto.routing.exceptions import InvalidDataError

		self.assertEqual(resolve_item_code(self.item), self.item)
		with self.assertRaises(InvalidDataError):
			resolve_item_code(f"missing-{self.suffix}")
