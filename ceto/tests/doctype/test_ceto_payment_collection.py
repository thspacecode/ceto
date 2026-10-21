"""Persistence record: Ceto Payment Collection.

The cart's single payment collection: named by the stable public
``pay_col_…`` id, linked uniquely to the cart's ``Ceto Cart Reference``
(one collection per cart lifetime, mirroring Medusa's upsert), carrying
the cart's current payable and one of the pinned collection statuses.
"""

import uuid

import frappe

from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoPaymentCollection(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.reference, self.quotation = self._make_cart()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _make_collection(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Payment Collection",
				"payment_collection_id": f"pay_col_{uuid.uuid4().hex}",
				"cart_reference": self.reference.name,
				"currency_code": "thb",
				"amount": 1100.0,
				"status": "not_paid",
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_collection_by_public_id(self):
		payment_collection_id = f"pay_col_{uuid.uuid4().hex}"
		self._make_collection(payment_collection_id=payment_collection_id)

		loaded = frappe.get_doc("Ceto Payment Collection", payment_collection_id)
		self.assertEqual(loaded.name, payment_collection_id)
		self.assertEqual(loaded.cart_reference, self.reference.name)

	def test_collection_id_is_unique(self):
		payment_collection_id = f"pay_col_{uuid.uuid4().hex}"
		self._make_collection(payment_collection_id=payment_collection_id)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_collection(
				payment_collection_id=payment_collection_id, cart_reference=self._second_cart()
			)

	def test_one_collection_per_cart(self):
		# The cart link is unique: Medusa's create-collection route upserts
		# (an existing cart collection is returned), so a second collection
		# for the same cart can never be valid.
		self._make_collection()
		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self._make_collection()

	def test_rejects_unknown_cart_reference(self):
		with self.assertRaises(frappe.exceptions.LinkValidationError):
			self._make_collection(cart_reference=f"cart_{uuid.uuid4().hex}")

	def test_records_the_current_payable(self):
		collection = self._make_collection(amount=1234.5, currency_code="thb")
		loaded = frappe.get_doc("Ceto Payment Collection", collection.name)
		self.assertEqual(frappe.utils.flt(loaded.amount), 1234.5)
		self.assertEqual(loaded.currency_code, "thb")

	def test_rejects_negative_amount(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_collection(amount=-1)

	def test_normalizes_the_currency_code(self):
		collection = self._make_collection(currency_code="THB")
		self.assertEqual(collection.currency_code, "thb")

	def test_rejects_non_iso_currency_code(self):
		for code in ("THBB", "th", "t1b", ""):
			with self.subTest(code=code):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_collection(currency_code=code)

	def test_status_is_pinned(self):
		# Status changes round-trip through save() on one collection; a
		# second insert per status would collide with the unique cart link.
		collection = self._make_collection()
		for status in (
			"not_paid",
			"awaiting",
			"authorized",
			"partially_authorized",
			"canceled",
			"completed",
			"failed",
		):
			collection.status = status
			collection.save(ignore_permissions=True)
			with self.subTest(status=status):
				self.assertEqual(collection.status, status)
		collection.status = "partially_captured"
		with self.assertRaises(frappe.exceptions.ValidationError):
			collection.save(ignore_permissions=True)

	def _second_cart(self):
		reference, _quotation = self._make_cart()
		return reference.name
