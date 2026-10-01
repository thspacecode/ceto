"""Phase 5 ledger record: Ceto Credit Wallet persistence and invariants.

Runs against the real ERPNext test site inside a single rolled-back
transaction: wallets validate their hash-only gift-card codes, keep code
hash and hint paired, scope both uniqueness rules by company, and never
hold a negative balance — the arithmetic the reservation-aware balances
build on.
"""

import hashlib
import uuid

import frappe

from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite


class TestCetoCreditWallet(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.company = self.masters.company
		self.currency = self.masters.settings.wizard_currency

	def _make_wallet(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Credit Wallet",
				"wallet_id": f"gc_{uuid.uuid4().hex}",
				"wallet_type": "Gift Card",
				"provider": "loyalty",
				"company": self.company,
				"customer": self.masters.customer,
				"currency": self.currency,
				"code_hash": hashlib.sha256(f"code-{uuid.uuid4().hex}".encode()).hexdigest(),
				"code_hint": "GC-****-1234",
				"credit_total": 100,
				"debit_total": 0,
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def _make_second_company(self) -> str:
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
		return company_name

	def test_names_wallet_by_its_public_id(self) -> None:
		wallet = self._make_wallet()

		loaded = frappe.get_doc("Ceto Credit Wallet", wallet.name)
		self.assertEqual(loaded.name, loaded.wallet_id)
		self.assertEqual(loaded.wallet_type, "Gift Card")
		self.assertEqual(loaded.provider, "loyalty")
		self.assertEqual(loaded.company, self.company)
		self.assertEqual(loaded.currency, self.currency)
		self.assertEqual(loaded.balance, 100)

	def test_gift_card_requires_code_hash_and_hint(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(code_hash=None, code_hint=None)

	def test_code_hash_and_hint_must_be_set_together(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(code_hint=None)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(code_hash=None)

	def test_code_hash_is_normalized_and_strict(self) -> None:
		digest = hashlib.sha256(b"some gift card").hexdigest()
		wallet = self._make_wallet(code_hash=digest.upper())
		self.assertEqual(wallet.code_hash, digest)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(code_hash="gc-code-1234")

	def _store_credit(self) -> dict:
		"""Fresh customer-owned store-credit overrides with a unique public id."""
		return {
			"wallet_id": f"sca_{uuid.uuid4().hex}",
			"wallet_type": "Store Credit",
			"customer": self.masters.customer,
			"code_hash": None,
			"code_hint": None,
		}

	def test_store_credit_wallet_requires_customer_or_code(self) -> None:
		store_credit = self._make_wallet(**self._store_credit())
		self.assertTrue(store_credit.name)

		claimable = self._make_wallet(
			wallet_id=f"sca_{uuid.uuid4().hex}",
			wallet_type="Store Credit",
			customer=None,
			code_hash=hashlib.sha256(b"claimable").hexdigest(),
			code_hint="SA-****-5678",
		)
		self.assertTrue(claimable.name)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(
				wallet_id=f"sca_{uuid.uuid4().hex}",
				wallet_type="Store Credit",
				customer=None,
				code_hash=None,
				code_hint=None,
			)

	def test_code_hash_is_unique_per_company(self) -> None:
		code_hash = hashlib.sha256(b"shared gift card").hexdigest()
		self._make_wallet(code_hash=code_hash)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(code_hash=code_hash)

	def test_store_credit_wallet_is_unique_per_company_customer_and_currency(self) -> None:
		self._make_wallet(**self._store_credit())

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(**self._store_credit())

	def test_uniqueness_is_scoped_by_company(self) -> None:
		code_hash = hashlib.sha256(b"per company code").hexdigest()
		self._make_wallet(code_hash=code_hash)
		self._make_wallet(**self._store_credit())

		other_company = self._make_second_company()
		self._make_wallet(company=other_company, code_hash=code_hash, customer=None)
		self._make_wallet(company=other_company, **self._store_credit())

	def test_balance_follows_credit_and_debit_totals(self) -> None:
		wallet = self._make_wallet(credit_total=250, debit_total=90)
		self.assertEqual(wallet.balance, 160)

		wallet.debit_total = 100
		wallet.save(ignore_permissions=True)
		self.assertEqual(wallet.balance, 150)

	def test_wallet_must_not_go_negative(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(debit_total=150)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_wallet(credit_total=-1)
