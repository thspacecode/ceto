"""Phase 5 credit serialization: ``gift_cards``, ``credit_lines`` and the totals carve-out.

Focused serializer view of the open credit holds (the apply/release/reconcile
behavior itself is covered by ``ceto.tests.services.carts.test_credits``). The
tests run against real ERPNext controllers on the test site inside a single
rolled-back transaction: the deduction rows and every total are ERPNext's own
output, the serializer only reports them.

The carved-out deductions reappear as positive holds, so the serialized cart
satisfies the Medusa summary identity
``total + discount_total + credit_line_total == subtotal + tax_total`` —
the invariant pinned throughout this module.
"""

import frappe
from frappe.utils import flt, get_datetime

from ceto.services.carts.credits import CartCredits
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import (
	ITEM_PRICE,
	ITEM_PRICE_B,
	SHIPPING_FLAT_RATE_AMOUNT,
	TAX_RATE,
	CartTestData,
	make_customer_with_user,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreAddGiftCardToCart,
	StoreAddStoreCreditsToCart,
	StoreCreateCart,
	StoreRemoveGiftCardFromCart,
)

LINE_TAX = flt(ITEM_PRICE * TAX_RATE / 100)
PAYABLE = flt(ITEM_PRICE * (1 + TAX_RATE / 100))
CART_PAYABLE = flt((ITEM_PRICE + ITEM_PRICE_B) * (1 + TAX_RATE / 100))
ITEM_TAX_TOTAL = flt((ITEM_PRICE + ITEM_PRICE_B) * TAX_RATE / 100)


def assert_summary_invariant(test: CetoTestSuite, cart: dict) -> None:
	"""Pin ``total + discount_total + credit_line_total == subtotal + tax_total``."""
	test.assertAlmostEqual(
		cart["total"] + cart["discount_total"] + cart["credit_line_total"],
		cart["subtotal"] + cart["tax_total"],
	)


def reservation_rows(quotation) -> list[dict]:
	"""Return the Quotation's reservation rows oldest-first."""
	return frappe.get_all(
		"Ceto Cart Credit Reservation",
		filters={"quotation": quotation.name},
		fields=["name", "status", "amount"],
		order_by="creation asc, name asc",
	)


class TestCartCreditSerialization(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()
		# The customer/user fixtures commit nowhere here, but Frappe throttles
		# user creation per hour; repeated runs of this module would trip it.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _cart(self, items: int = 1, *, with_shipping: bool = False) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			for index in range(items):
				variant = self.masters.item if index == 0 else self.masters.other_item
				self.service.add_line_item(
					reference.cart_id, StoreAddCartLineItem(variant_id=variant, quantity=1)
				)
			if with_shipping:
				self.service.set_shipping_method(
					reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
				)
			return self.service.retrieve(reference.cart_id)

	def _apply_gift_card(self, cart_id: str, code: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.add_gift_card(cart_id, StoreAddGiftCardToCart(code=code))

	def _remove_gift_card(self, cart_id: str, code: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.remove_gift_card(cart_id, StoreRemoveGiftCardFromCart(code=code))

	def _apply_store_credits(self, cart_id: str, email: str, amount: float | None) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			return self.service.add_store_credits(cart_id, StoreAddStoreCreditsToCart(amount=amount))

	def test_cart_without_credits_reports_empty_loyalty_totals(self) -> None:
		reference, quotation = self._cart()

		cart = CartSerializer().serialize(reference, quotation)

		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual(cart["credit_lines"], [])
		self.assertEqual(cart["gift_card_total"], 0)
		self.assertEqual(cart["gift_card_tax_total"], 0)
		self.assertEqual(cart["credit_line_total"], 0)
		# Without credits the identity is the pre-Phase-5 one.
		assert_summary_invariant(self, cart)

	def test_gift_card_serializes_the_hint_and_one_credit_line(self) -> None:
		code = f"GC-SER-{self.masters.suffix}"
		wallet = self.masters.make_gift_card(code, credit_total=100.0)
		reference, quotation = self._cart()
		reference, quotation = self._apply_gift_card(reference.cart_id, code)
		reservation = frappe.get_all(
			"Ceto Cart Credit Reservation",
			filters={"quotation": quotation.name, "status": "Reserved"},
			fields=["credit_line_id", "amount", "creation", "modified"],
		)[0]

		cart = CartSerializer().serialize(reference, quotation)

		# The card is stored hash-only: the serialized code is the masked
		# hint, and neither the plaintext code nor the hash is serialized.
		self.assertEqual([gift_card["code"] for gift_card in cart["gift_cards"]], [f"GC-****-{code[-4:]}"])
		self.assertEqual(set(cart["gift_cards"][0]), {"code"})
		self.assertNotIn(code, frappe.as_json(cart))
		self.assertNotIn(wallet, frappe.as_json(cart["gift_cards"]))
		self.assertEqual(len(cart["credit_lines"]), 1)
		line = cart["credit_lines"][0]
		self.assertEqual(line["id"], reservation["credit_line_id"])
		self.assertEqual(line["cart_id"], reference.cart_id)
		self.assertEqual(line["amount"], reservation["amount"])
		self.assertEqual(line["reference"], "gift-card")
		self.assertEqual(line["reference_id"], wallet)
		self.assertEqual(line["created_at"], get_datetime(reservation["creation"]).isoformat())
		self.assertEqual(line["updated_at"], get_datetime(reservation["modified"]).isoformat())
		# The capped hold equals the whole pre-deduction payable; ``total`` is
		# ERPNext's own deducted grand total.
		self.assertAlmostEqual(cart["gift_card_total"], PAYABLE)
		self.assertAlmostEqual(cart["credit_line_total"], PAYABLE)
		self.assertAlmostEqual(cart["total"], 0)
		assert_summary_invariant(self, cart)

	def test_deduction_is_carved_out_of_item_tax(self) -> None:
		code = f"GC-CARVE-{self.masters.suffix}"
		self.masters.make_gift_card(code, credit_total=100.0)
		reference, quotation = self._cart(with_shipping=True)
		reference, quotation = self._apply_gift_card(reference.cart_id, code)

		cart = CartSerializer().serialize(reference, quotation)

		# The shipping charge and the negative deduction row both spread over
		# the item rows through ERPNext's ``Actual`` allocation, and both are
		# carved out: every tax field carries only the template's item tax.
		self.assertAlmostEqual(cart["tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["item_tax_total"], LINE_TAX)
		self.assertAlmostEqual(cart["original_tax_total"], LINE_TAX)
		self.assertEqual(len(cart["items"]), 1)
		self.assertAlmostEqual(cart["items"][0]["tax_total"], LINE_TAX)
		# The charges stay folded into ERPNext's totals: ``subtotal`` carries
		# the shipping, ``total`` the deduction (zero here — the 100 card is
		# capped by the 77.5 payable).
		self.assertAlmostEqual(cart["subtotal"], ITEM_PRICE + SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(cart["total"], 0)
		assert_summary_invariant(self, cart)

	def test_mixed_holds_serialize_in_application_order(self) -> None:
		code = f"GC-MIX-{self.masters.suffix}"
		gift_wallet = self.masters.make_gift_card(code, credit_total=40.0)
		email, customer = make_customer_with_user("serializer")
		credit_wallet = self.masters.make_store_credit_wallet(customer=customer, credit_total=20.0)
		reference, quotation = self._cart(items=2)
		reference, quotation = self._apply_gift_card(reference.cart_id, code)
		reference, quotation = self._apply_store_credits(reference.cart_id, email, None)

		cart = CartSerializer().serialize(reference, quotation)

		self.assertEqual([line["reference"] for line in cart["credit_lines"]], ["gift-card", "store-credit"])
		self.assertEqual(
			[line["reference_id"] for line in cart["credit_lines"]], [gift_wallet, credit_wallet]
		)
		self.assertAlmostEqual(cart["credit_lines"][0]["amount"], 40.0)
		self.assertAlmostEqual(cart["credit_lines"][1]["amount"], 20.0)
		# ``gift_card_total`` counts only the gift-card subset;
		# ``credit_line_total`` counts every open hold.
		self.assertAlmostEqual(cart["gift_card_total"], 40.0)
		self.assertAlmostEqual(cart["credit_line_total"], 60.0)
		self.assertAlmostEqual(cart["tax_total"], ITEM_TAX_TOTAL)
		# 84 net + 8.4 tax - 60 held.
		self.assertAlmostEqual(cart["total"], flt(ITEM_PRICE + ITEM_PRICE_B + ITEM_TAX_TOTAL - 60.0))
		assert_summary_invariant(self, cart)

	def test_released_holds_stop_serializing(self) -> None:
		code = f"GC-REL-{self.masters.suffix}"
		self.masters.make_gift_card(code, credit_total=40.0)
		email, customer = make_customer_with_user("release")
		self.masters.make_store_credit_wallet(customer=customer, credit_total=20.0)
		reference, quotation = self._cart(items=2)
		reference, quotation = self._apply_gift_card(reference.cart_id, code)
		reference, quotation = self._apply_store_credits(reference.cart_id, email, 10)
		self.assertEqual([row["status"] for row in reservation_rows(quotation)], ["Reserved", "Reserved"])

		reference, quotation = self._remove_gift_card(reference.cart_id, code)

		# The Released reservation stays on the Quotation but drops out of the
		# public collections and totals.
		self.assertEqual(
			[row["status"] for row in reservation_rows(quotation)],
			["Released", "Reserved"],
		)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["gift_cards"], [])
		self.assertEqual([line["reference"] for line in cart["credit_lines"]], ["store-credit"])
		self.assertAlmostEqual(cart["gift_card_total"], 0)
		self.assertAlmostEqual(cart["credit_line_total"], 10)
		self.assertAlmostEqual(cart["total"], flt(CART_PAYABLE - 10))
		assert_summary_invariant(self, cart)

	def test_store_credit_holds_replace_without_ghost_lines(self) -> None:
		email, customer = make_customer_with_user("replace")
		self.masters.make_store_credit_wallet(customer=customer, credit_total=20.0)
		reference, quotation = self._cart()
		reference, quotation = self._apply_store_credits(reference.cart_id, email, 10)
		reference, quotation = self._apply_store_credits(reference.cart_id, email, 15)

		cart = CartSerializer().serialize(reference, quotation)

		# The replaced hold is Released and no longer reports.
		self.assertEqual([line["amount"] for line in cart["credit_lines"]], [15.0])
		self.assertAlmostEqual(cart["credit_line_total"], 15)
		self.assertAlmostEqual(cart["total"], flt(PAYABLE - 15))
		assert_summary_invariant(self, cart)
		self.assertEqual(len(CartCredits.deduction_rows(quotation)), 1)
