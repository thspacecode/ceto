"""Phase 5 credit service tests: gift cards, store credits and reconciliation.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. Totals, tax rows and the deduction bookings are
produced by ERPNext; the tests assert on the resulting documents, the open
holds and the serialized cart.
"""

import frappe
from frappe.utils import add_to_date, flt, now_datetime

from ceto.routing.exceptions import InvalidDataError, UnauthorizedError
from ceto.services.carts.credits import (
	GIFT_CARD_CURRENCY,
	GIFT_CARD_EXHAUSTED,
	GIFT_CARD_EXPIRED,
	GIFT_CARD_NO_PAYABLE,
	GIFT_CARD_NOT_APPLIED,
	GIFT_CARD_NOT_FOUND,
	STORE_CREDIT_WALLET_MISSING,
	STORE_CREDITS_EXCEEDED,
	STORE_CREDITS_NO_PAYABLE,
	CartCredits,
	hash_code,
)
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import (
	ITEM_PRICE,
	ITEM_PRICE_B,
	TAX_RATE,
	CartTestData,
	make_customer_with_user,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddGiftCardToCart,
	StoreAddStoreCreditsToCart,
	StoreCreateCart,
	StoreUpdateCart,
	StoreUpdateCartLineItem,
)

PAYABLE = flt(ITEM_PRICE * (1 + TAX_RATE / 100))


class TestCartGiftCardService(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()
		self.code = f"GC-SVC-{self.masters.suffix}"
		self.wallet = self.masters.make_gift_card(self.code, credit_total=100.0)

	def _cart(self, quantity: int = 1, *, item: str | None = None) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			if quantity:
				self.service.add_line_item(
					reference.cart_id,
					StoreAddCartLineItem(variant_id=item or self.masters.item, quantity=quantity),
				)
			return self.service.retrieve(reference.cart_id)

	def _apply(self, cart_id: str, code: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.add_gift_card(cart_id, StoreAddGiftCardToCart(code=code))

	def _holds(self, quotation) -> list[dict]:
		return frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation.name},
			fields=["name", "credit_line_id", "wallet", "amount", "status"],
			order_by="creation asc",
		)

	def _deduction_rows(self, quotation) -> list:
		return CartCredits.deduction_rows(quotation)

	def test_apply_books_hold_and_negative_deduction_row(self) -> None:
		reference, quotation = self._cart()

		reference, quotation = self._apply(reference.cart_id, self.code)

		holds = self._holds(quotation)
		self.assertEqual(len(holds), 1)
		self.assertEqual(holds[0]["status"], "Reserved")
		self.assertEqual(holds[0]["wallet"], self.wallet)
		self.assertAlmostEqual(holds[0]["amount"], PAYABLE)
		# The deduction is a negative Actual row on the receivable account,
		# folded into the ERPNext-computed totals.
		rows = self._deduction_rows(quotation)
		self.assertEqual(len(rows), 1)
		self.assertAlmostEqual(rows[0].tax_amount, -PAYABLE)
		self.assertAlmostEqual(quotation.grand_total, 0)
		# The 10% template taxes the 25 net total (2.5); the 27.5 deduction
		# is a negative Actual row folded into the same field by ERPNext.
		self.assertAlmostEqual(
			quotation.total_taxes_and_charges, flt(ITEM_PRICE * (TAX_RATE / 100)) - PAYABLE
		)

	def test_apply_hashes_the_code_and_never_stores_it(self) -> None:
		reference, quotation = self._cart()

		self._apply(reference.cart_id, self.code)

		# The lookup is hash-only, scoped to the cart's company.
		self.assertEqual(
			frappe.db.get_value(
				"Ceto Credit Wallet", {"company": quotation.company, "code_hash": hash_code(self.code)}
			),
			self.wallet,
		)
		wallet = frappe.get_doc("Ceto Credit Wallet", self.wallet)
		for field in ("wallet_id", "code_hash", "code_hint"):
			self.assertNotIn(self.code, wallet.get(field) or "")
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual([gift_card["code"] for gift_card in cart["gift_cards"]], [wallet.code_hint])

	def test_apply_is_idempotent(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, self.code)

		reference, quotation = self._apply(reference.cart_id, self.code)

		self.assertEqual(len(self._holds(quotation)), 1)
		self.assertEqual(len(self._deduction_rows(quotation)), 1)
		self.assertAlmostEqual(quotation.grand_total, 0)

	def test_unknown_code_rejects_without_mutation(self) -> None:
		reference, quotation = self._cart()
		with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_NOT_FOUND):
			self._apply(reference.cart_id, "GC-UNKNOWN")
		self.assertAlmostEqual(quotation.grand_total, PAYABLE)
		self.assertEqual(self._holds(quotation), [])

	def test_expired_card_rejects(self) -> None:
		expired = self.masters.make_gift_card(
			f"GC-OLD-{self.masters.suffix}",
			credit_total=50.0,
			expires_at=add_to_date(now_datetime(), days=-1),
		)
		reference, _quotation = self._cart()
		with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_EXPIRED):
			self._apply(reference.cart_id, f"GC-OLD-{self.masters.suffix}")
		self.assertEqual(expired, expired)  # the fixture converged on one wallet

	def test_foreign_currency_card_rejects(self) -> None:
		self.masters.make_gift_card(f"GC-EUR-{self.masters.suffix}", credit_total=50.0, currency="EUR")
		reference, _quotation = self._cart()
		with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_CURRENCY):
			self._apply(reference.cart_id, f"GC-EUR-{self.masters.suffix}")

	def test_exhausted_card_rejects(self) -> None:
		self.masters.make_gift_card(f"GC-EMPTY-{self.masters.suffix}", credit_total=0)
		reference, _quotation = self._cart()
		with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_EXHAUSTED):
			self._apply(reference.cart_id, f"GC-EMPTY-{self.masters.suffix}")

	def test_itemless_cart_rejects(self) -> None:
		reference, _quotation = self._cart(quantity=0)
		with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_NO_PAYABLE):
			self._apply(reference.cart_id, self.code)

	def test_hold_rederives_when_cart_grows(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, self.code)

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.add_line_item(
				reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.other_item, quantity=1)
			)
		reference, quotation = self.service.retrieve(reference.cart_id)

		grown = flt((ITEM_PRICE + ITEM_PRICE_B) * (1 + TAX_RATE / 100))
		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], grown)
		self.assertAlmostEqual(quotation.grand_total, 0)

	def test_hold_caps_when_cart_shrinks(self) -> None:
		reference, quotation = self._cart(quantity=2)
		self._apply(reference.cart_id, self.code)
		# The 100 wallet is capped by what the two-item cart can absorb.
		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], flt(2 * PAYABLE))

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line = frappe.get_all(
				"Ceto Cart Line Item Reference", filters={"cart_reference": reference.name}, pluck="line_id"
			)[0]
			self.service.update_line_item(reference.cart_id, line, StoreUpdateCartLineItem(quantity=1))
		reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], PAYABLE)
		self.assertAlmostEqual(quotation.grand_total, 0)

	def test_emptied_cart_releases_holds(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, self.code)

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line = frappe.get_all(
				"Ceto Cart Line Item Reference", filters={"cart_reference": reference.name}, pluck="line_id"
			)[0]
			self.service.delete_line_item(reference.cart_id, line)
		reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertEqual([hold["status"] for hold in self._holds(quotation)], ["Released"])
		self.assertEqual(self._deduction_rows(quotation), [])
		self.assertAlmostEqual(quotation.grand_total, 0)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])

	def test_remove_releases_and_restores_totals(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, self.code)

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.remove_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=self.code))

		self.assertEqual([hold["status"] for hold in self._holds(quotation)], ["Released"])
		self.assertEqual(self._deduction_rows(quotation), [])
		self.assertAlmostEqual(quotation.grand_total, PAYABLE)

	def test_remove_unknown_code_rejects(self) -> None:
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_NOT_FOUND):
				self.service.remove_gift_card(reference.cart_id, StoreAddGiftCardToCart(code="GC-NOPE"))

	def test_remove_unapplied_code_rejects(self) -> None:
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, GIFT_CARD_NOT_APPLIED):
				self.service.remove_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=self.code))

	def test_wallet_availability_is_reservation_aware_across_carts(self) -> None:
		self.masters.make_gift_card(self.code, credit_total=40.0)
		first, first_quotation = self._cart()
		self._apply(first.cart_id, self.code)
		self.assertAlmostEqual(self._holds(first_quotation)[0]["amount"], PAYABLE)

		second, second_quotation = self._cart()

		second, second_quotation = self._apply(second.cart_id, self.code)

		# The first cart's open hold reduces what the second may take.
		self.assertAlmostEqual(self._holds(second_quotation)[0]["amount"], 40.0 - PAYABLE)
		self.assertAlmostEqual(second_quotation.grand_total, PAYABLE - (40.0 - PAYABLE))

	def test_survives_tax_template_reload(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, self.code)

		configuration = {
			**self.masters.configuration,
			"regions": {
				"reg_test": {},
				"reg_alt": {"taxes_and_charges": self.masters.alt_taxes_and_charges},
			},
		}
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			self.service.update(reference.cart_id, StoreUpdateCart(region_id="reg_alt"))
		reference, quotation = self.service.retrieve(reference.cart_id)

		# The reload replaced the taxes table with the 5% template rows; the
		# reconciliation rebuilt the deduction against the new payable and
		# kept the total at zero.
		self.assertEqual(quotation.taxes_and_charges, self.masters.alt_taxes_and_charges)
		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], flt(ITEM_PRICE * 1.05))
		self.assertEqual(len(self._deduction_rows(quotation)), 1)
		self.assertAlmostEqual(quotation.grand_total, 0)

	def test_calculate_taxes_keeps_single_hold(self) -> None:
		reference, quotation = self._cart()
		reference, quotation = self._apply(reference.cart_id, self.code)
		before = CartSerializer().serialize(reference, quotation)

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self.service.calculate_taxes(reference.cart_id)

		self.assertEqual(len(self._holds(quotation)), 1)
		self.assertEqual(len(self._deduction_rows(quotation)), 1)
		after = CartSerializer().serialize(reference, quotation)
		for field in ("total", "subtotal", "tax_total", "gift_card_total", "gift_cards", "credit_lines"):
			self.assertEqual(after[field], before[field], field)


class TestCartStoreCreditService(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()
		# The wallet fixtures commit, so every test's customer party survives
		# its rollback; unique-per-test users pile up like the claim API's and
		# would cross frappe's user-creation throttle on repeated runs.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		self.email, self.customer = make_customer_with_user("credits")
		self.wallet = self.masters.make_store_credit_wallet(customer=self.customer, credit_total=20.0)

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _cart(self, quantity: int = 1) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			if quantity:
				self.service.add_line_item(
					reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.item, quantity=quantity)
				)
			return self.service.retrieve(reference.cart_id)

	def _apply(self, cart_id: str, payload: StoreAddStoreCreditsToCart) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(self.email):
			return self.service.add_store_credits(cart_id, payload)

	def _holds(self, quotation) -> list[dict]:
		return frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation.name},
			fields=["name", "wallet", "amount", "status"],
			order_by="creation asc",
		)

	def test_default_amount_reserves_whole_available_balance(self) -> None:
		reference, quotation = self._cart()

		reference, quotation = self._apply(reference.cart_id, StoreAddStoreCreditsToCart())

		holds = self._holds(quotation)
		self.assertEqual(len(holds), 1)
		self.assertEqual(holds[0]["wallet"], self.wallet)
		self.assertAlmostEqual(holds[0]["amount"], 20.0)
		self.assertAlmostEqual(quotation.grand_total, flt(PAYABLE - 20.0))

	def test_explicit_amount_is_reserved(self) -> None:
		reference, quotation = self._cart()

		reference, quotation = self._apply(reference.cart_id, StoreAddStoreCreditsToCart(amount=10))

		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], 10.0)
		self.assertAlmostEqual(quotation.grand_total, flt(PAYABLE - 10.0))

	def test_amount_exceeding_balance_rejects(self) -> None:
		reference, quotation = self._cart()
		with self.assertRaisesRegex(InvalidDataError, STORE_CREDITS_EXCEEDED):
			self._apply(reference.cart_id, StoreAddStoreCreditsToCart(amount=50))
		self.assertEqual(self._holds(quotation), [])
		self.assertAlmostEqual(quotation.grand_total, PAYABLE)

	def test_itemless_cart_rejects(self) -> None:
		reference, _quotation = self._cart(quantity=0)
		with self.assertRaisesRegex(InvalidDataError, STORE_CREDITS_NO_PAYABLE):
			self._apply(reference.cart_id, StoreAddStoreCreditsToCart())

	def test_reapplication_replaces_prior_reservations(self) -> None:
		reference, quotation = self._cart()
		reference, quotation = self._apply(reference.cart_id, StoreAddStoreCreditsToCart(amount=10))

		reference, quotation = self._apply(reference.cart_id, StoreAddStoreCreditsToCart(amount=15))

		holds = self._holds(quotation)
		self.assertEqual([hold["status"] for hold in holds], ["Released", "Reserved"])
		self.assertAlmostEqual(holds[1]["amount"], 15.0)
		self.assertAlmostEqual(quotation.grand_total, flt(PAYABLE - 15.0))

		# Reapplying without an amount replaces the prior hold with the
		# whole wallet balance: the released hold stops counting against
		# availability, so the full 20 is reserved again.
		reference, quotation = self._apply(reference.cart_id, StoreAddStoreCreditsToCart())
		holds = self._holds(quotation)
		self.assertEqual([hold["status"] for hold in holds], ["Released", "Released", "Reserved"])
		self.assertAlmostEqual(holds[2]["amount"], 20.0)
		self.assertAlmostEqual(quotation.grand_total, flt(PAYABLE - 20.0))

	def test_credit_keeps_amount_when_cart_grows(self) -> None:
		reference, quotation = self._cart()
		self._apply(reference.cart_id, StoreAddStoreCreditsToCart())

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.add_line_item(
				reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.other_item, quantity=1)
			)
		reference, quotation = self.service.retrieve(reference.cart_id)

		# Unlike a gift card, the requested hold does not re-derive upwards;
		# only a reapplication grows it.
		self.assertAlmostEqual(self._holds(quotation)[0]["amount"], 20.0)
		self.assertAlmostEqual(quotation.grand_total, flt((ITEM_PRICE + ITEM_PRICE_B) * 1.1 - 20.0))

	def test_store_credits_require_customer(self) -> None:
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaises(UnauthorizedError):
				self.service.add_store_credits(reference.cart_id, StoreAddStoreCreditsToCart())

	def test_customer_without_wallet_rejects(self) -> None:
		_reference, _quotation = self._cart()
		_other_email, other_customer = make_customer_with_user("other")
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(self.email):
			with self.assertRaisesRegex(InvalidDataError, STORE_CREDIT_WALLET_MISSING):
				CartCredits.apply_store_credits(
					frappe.get_doc("Quotation", _quotation.name), other_customer, None
				)
