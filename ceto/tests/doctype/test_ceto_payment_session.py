"""Persistence record: Ceto Payment Session.

One provider payment attempt on a collection: named by the stable public
``payses_…`` id, snapshotting the payable (``amount`` + ``currency_code``)
and ``provider_id`` idempotent creation keys on, with at most one current
session per collection — the invariant the staleness semantics of
``ceto.services.payments.collections`` rely on.
"""

import json
import uuid

import frappe

from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoPaymentSession(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.reference, self.quotation = self._make_cart()
		self.collection = self._make_collection()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _make_collection(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Ceto Payment Collection",
					"payment_collection_id": f"pay_col_{uuid.uuid4().hex}",
					"cart_reference": self.reference.name,
					"currency_code": "thb",
					"amount": 1100.0,
					"status": "not_paid",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_session(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Payment Session",
				"payment_session_id": f"payses_{uuid.uuid4().hex}",
				"payment_collection": self.collection,
				"provider_id": "pp_beam_beam",
				"amount": 1100.0,
				"currency_code": "thb",
				"status": "pending",
				"is_current": 0,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_session_by_public_id(self):
		payment_session_id = f"payses_{uuid.uuid4().hex}"
		self._make_session(payment_session_id=payment_session_id)

		loaded = frappe.get_doc("Ceto Payment Session", payment_session_id)
		self.assertEqual(loaded.name, payment_session_id)
		self.assertEqual(loaded.payment_collection, self.collection)

	def test_session_id_is_unique(self):
		payment_session_id = f"payses_{uuid.uuid4().hex}"
		self._make_session(payment_session_id=payment_session_id)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_session(payment_session_id=payment_session_id)

	def test_rejects_unknown_collection(self):
		with self.assertRaises(frappe.exceptions.LinkValidationError):
			self._make_session(payment_collection=f"pay_col_{uuid.uuid4().hex}")

	def test_amount_must_be_positive(self):
		for amount in (0, -100):
			with self.subTest(amount=amount):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_session(amount=amount)

	def test_normalizes_the_currency_code(self):
		session = self._make_session(currency_code="THB")
		self.assertEqual(session.currency_code, "thb")

	def test_rejects_non_iso_currency_code(self):
		for code in ("THBB", "th", "t1b"):
			with self.subTest(code=code):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_session(currency_code=code)

	def test_status_is_pinned(self):
		for status in (
			"pending",
			"pending_authorization",
			"authorized",
			"captured",
			"requires_more",
			"error",
			"canceled",
		):
			with self.subTest(status=status):
				self._make_session(status=status)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_session(status="partially_captured")

	def test_provider_data_stores_a_json_object(self):
		session = self._make_session(provider_data=json.dumps({"charge_id": "ch_1", "qr": "x"}))
		self.assertEqual(json.loads(session.provider_data), {"charge_id": "ch_1", "qr": "x"})

	def test_provider_data_must_be_valid_json(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_session(provider_data="{not json")

	def test_provider_data_must_be_a_json_object(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_session(provider_data=json.dumps(["ch_1"]))
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_session(provider_data=json.dumps("ch_1"))

	def test_is_current_defaults_to_stale(self):
		session = self._make_session()
		self.assertEqual(session.is_current, 0)

	def test_one_current_session_per_collection(self):
		first = self._make_session(is_current=1)
		# A second current session for the same collection is refused, even
		# with a different provider, amount or id.
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_session(is_current=1, provider_id="pp_stripe_stripe", amount=900)

		# Staling the first releases the slot.
		frappe.db.set_value("Ceto Payment Session", first.name, "is_current", 0)
		second = self._make_session(is_current=1)
		self.assertEqual(second.is_current, 1)

	def test_current_sessions_are_scoped_to_their_collection(self):
		# Two collections (two carts) may each hold their own current session.
		self._make_session(is_current=1)
		reference, _quotation = self._make_cart()
		collection = (
			frappe.get_doc(
				{
					"doctype": "Ceto Payment Collection",
					"payment_collection_id": f"pay_col_{uuid.uuid4().hex}",
					"cart_reference": reference.name,
					"currency_code": "thb",
					"amount": 1100.0,
					"status": "not_paid",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		session = self._make_session(payment_collection=collection, is_current=1)
		self.assertEqual(session.is_current, 1)
