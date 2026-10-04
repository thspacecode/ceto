"""Phase 5 reservation record: Ceto Cart Credit Reservation persistence.

Runs a real guest cart (``CartService``) against real wallets on the test site
inside a single rolled-back transaction: reservations are named by their
public credit-line id, must match the cart Quotation's company and currency,
and can never exceed the wallet's reservation-aware available balance.
"""

import hashlib
import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class TestCetoCartCreditReservation(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.currency = self.masters.settings.wizard_currency
		self.wallet = self._make_wallet()
		self.reference, self.quotation = self._make_cart()

	def _make_cart(self):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return CartService().create(StoreCreateCart(email="guest@example.com"))

	def _make_wallet(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Credit Wallet",
				"wallet_id": f"sca_{uuid.uuid4().hex}",
				"wallet_type": "Store Credit",
				"provider": "loyalty",
				"company": self.masters.company,
				"customer": self.masters.customer,
				"currency": self.currency,
				"credit_total": 100,
				"debit_total": 0,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _make_reservation(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Cart Credit Reservation",
				"credit_line_id": f"cl_{uuid.uuid4().hex}",
				"wallet": self.wallet.name,
				"quotation": self.quotation.name,
				"currency": self.currency,
				"amount": 40,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _append_quotation_item(self) -> None:
		self.quotation.append("items", {"item_code": self.masters.item, "qty": 1})
		self.quotation.flags.ignore_mandatory = True
		self.quotation.save(ignore_permissions=True)

	def _make_second_company_wallet(self) -> str:
		company_name = f"Ceto Test Wallet {uuid.uuid4().hex[:8]}"
		frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": company_name,
				"country": self.masters.settings.wizard_country,
				"default_currency": self.currency,
				"create_chart_of_accounts_based_on": "Standard Template",
				"chart_of_accounts": "Standard",
			}
		).insert(ignore_permissions=True)
		return self._make_wallet(company=company_name).name

	def test_names_reservation_by_credit_line_id(self) -> None:
		reservation = self._make_reservation(amount=60)

		loaded = frappe.get_doc("Ceto Cart Credit Reservation", reservation.name)
		self.assertEqual(loaded.name, loaded.credit_line_id)
		self.assertEqual(loaded.wallet, self.wallet.name)
		self.assertEqual(loaded.quotation, self.quotation.name)
		self.assertEqual(loaded.currency, self.currency)
		self.assertEqual(loaded.status, "Reserved")

	def test_amount_must_be_positive(self) -> None:
		for amount in (0, -5):
			with self.subTest(amount=amount), self.assertRaises(frappe.exceptions.ValidationError):
				self._make_reservation(amount=amount)

	def test_rejects_unknown_wallet_and_quotation(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(wallet=f"sca_missing-{uuid.uuid4().hex}")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(quotation=f"QUO-missing-{uuid.uuid4().hex}")

	def test_rejects_currency_mismatch(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(currency="EUR")

	def test_rejects_wallet_from_another_company(self) -> None:
		foreign_wallet = self._make_second_company_wallet()

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(wallet=foreign_wallet)

	def test_rejects_quotation_that_is_not_a_cart(self) -> None:
		frappe.db.set_value("Quotation", self.quotation.name, "order_type", "Sales", update_modified=False)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation()

	def test_expired_wallet_cannot_take_reservations(self) -> None:
		expired = self._make_wallet(
			wallet_type="Gift Card",
			code_hash=hashlib.sha256(b"expired").hexdigest(),
			code_hint="GC-****-0001",
			expires_at=add_to_date(now_datetime(), days=-1),
		)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(wallet=expired.name)

		future = self._make_wallet(
			wallet_type="Gift Card",
			code_hash=hashlib.sha256(b"future").hexdigest(),
			code_hint="GC-****-0002",
			expires_at=add_to_date(now_datetime(), days=1),
		)
		self.assertTrue(self._make_reservation(wallet=future.name).name)

	def test_reservation_survives_submission_but_not_cancellation(self) -> None:
		self._append_quotation_item()
		self.quotation.submit()
		self.assertTrue(self._make_reservation(amount=10).name)

		self.quotation.cancel()
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(amount=5)

	def test_available_balance_is_reservation_aware(self) -> None:
		first = self._make_reservation(amount=60)
		self.assertTrue(self._make_reservation(amount=40).name)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(amount=1)

		first.status = "Released"
		first.save(ignore_permissions=True)
		self.assertTrue(self._make_reservation(amount=60).name)

	def test_available_balance_derives_from_ledger_totals_not_the_snapshot(self) -> None:
		# The ledger backs the hold (100); a stale-low snapshot (10) must
		# not reject it.
		frappe.db.set_value("Ceto Credit Wallet", self.wallet.name, "balance", 10, update_modified=False)
		self.assertTrue(self._make_reservation(amount=40).name)

		# The other way round: a stale-high snapshot (500) must not admit a
		# hold beyond what the ledger (50) still backs. A gift-card wallet
		# avoids the store-credit uniqueness rule (one per customer).
		other = self._make_wallet(
			wallet_type="Gift Card",
			code_hash=hashlib.sha256(b"stale high snapshot").hexdigest(),
			code_hint="GC-****-9999",
			credit_total=50,
		)
		frappe.db.set_value("Ceto Credit Wallet", other.name, "balance", 500, update_modified=False)
		self._make_reservation(wallet=other.name, amount=40)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reservation(wallet=other.name, amount=20)

	def test_reservation_update_counts_the_other_holds(self) -> None:
		first = self._make_reservation(amount=60)
		self._make_reservation(amount=40)

		first.amount = 90
		with self.assertRaises(frappe.exceptions.ValidationError):
			first.save(ignore_permissions=True)

	def test_wallet_with_reservations_cannot_be_deleted(self) -> None:
		self._make_reservation()

		with self.assertRaises(frappe.exceptions.LinkExistsError):
			frappe.delete_doc("Ceto Credit Wallet", self.wallet.name, ignore_permissions=True)

	def test_cart_reference_delete_cleans_up_reservations(self) -> None:
		reservation = self._make_reservation()

		frappe.delete_doc("Ceto Cart Reference", self.reference.name, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Ceto Cart Credit Reservation", reservation.name))
