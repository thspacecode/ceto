"""Phase 4 promotion service tests: coupon application, removal and limits.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. Pricing Rule and Coupon Code resolution, discounts
and Quotation totals are produced by ERPNext; the tests only assert on the
resulting documents.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from ceto.routing.exceptions import InvalidDataError, NotAllowedError
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import ITEM_PRICE, CartTestData
from ceto.tests.testsuite import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCartAddPromotion,
	StoreCartRemovePromotion,
	StoreCreateCart,
	StoreUpdateCart,
)

DISCOUNT_PERCENTAGE = 10.0


class TestCartPromotions(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData.shared()
		self.service = CartService()
		self.discount_code = self._make_coupon("SAVE10", DISCOUNT_PERCENTAGE)
		# Most rejection paths only need a distinct public code. Creating a
		# second matching Pricing Rule before a cart has a coupon makes ERPNext
		# correctly report ambiguous rules while the initial line is priced.
		self.other_code = f"SAVE20{self.masters.suffix}"

	def _make_coupon(self, label: str, percentage: float, **overrides) -> str:
		rule = {
			"doctype": "Pricing Rule",
			"title": f"Ceto Coupon {label} {self.masters.suffix}",
			"apply_on": "Item Code",
			"items": [{"item_code": self.masters.item}],
			"coupon_code_based": 1,
			"selling": 1,
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": percentage,
			"company": self.masters.company.name,
			"for_price_list": self.masters.price_list,
			"currency": "USD",
			"priority": {"SAVE10": 1, "SAVE20": 2, "OLDE": 3, "MAXED": 4, "APISAVE": 1, "APIOTHER": 2}[label],
			"valid_from": today(),
		}
		rule.update({key: overrides.pop(key) for key in ("valid_upto",) if key in overrides})
		rule = frappe.get_doc(rule).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": f"Ceto {label} {self.masters.suffix}",
				"coupon_code": f"{label}{self.masters.suffix}",
				"coupon_type": "Promotional",
				"pricing_rule": rule.name,
				"valid_from": today(),
				**overrides,
			}
		).insert(ignore_permissions=True)
		return f"{label}{self.masters.suffix}"

	def _create_cart(self, **payload) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.create(StoreCreateCart(**payload))

	def _create_cart_with_line(self) -> tuple:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
		return self.service.retrieve(reference.cart_id)

	def _apply(self, cart_id: str, *codes: str):
		return self.service.add_promotions(cart_id, StoreCartAddPromotion(promo_codes=list(codes)))

	def _remove(self, cart_id: str, *codes: str):
		return self.service.remove_promotions(cart_id, StoreCartRemovePromotion(promo_codes=list(codes)))

	def test_apply_links_coupon_and_discounts_via_erpnext(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._apply(reference.cart_id, self.discount_code)
			reference, quotation = self.service.retrieve(reference.cart_id)

		coupon_name = frappe.db.get_value("Coupon Code", {"coupon_code": self.discount_code}, "name")
		self.assertEqual(quotation.coupon_code, coupon_name)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(
			cart["promotions"], [{"id": coupon_name, "code": self.discount_code, "is_automatic": False}]
		)
		# The discount itself is ERPNext's pricing-rule output: the item rate
		# drops by the rule's percentage.
		self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE * (1 - DISCOUNT_PERCENTAGE / 100))
		self.assertAlmostEqual(cart["items"][0]["unit_price"], ITEM_PRICE * 0.9)

	def test_apply_is_idempotent_for_the_same_code(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._apply(reference.cart_id, self.discount_code, self.discount_code)
			self._apply(reference.cart_id, self.discount_code)
			_reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNotNone(quotation.coupon_code)

	def test_apply_unknown_code_is_rejected_without_mutation(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Unknown promotion code"):
				self._apply(reference.cart_id, f"NOPE{self.masters.suffix}")
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.coupon_code)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["promotions"], [])
		self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE)

	def test_apply_expired_coupon_is_rejected(self) -> None:
		expired = self._make_coupon("OLDE", 5.0, valid_upto=add_days(today(), -1))
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "validity has expired"):
				self._apply(reference.cart_id, expired)
			_reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.coupon_code)

	def test_apply_exhausted_coupon_is_rejected(self) -> None:
		exhausted = self._make_coupon("MAXED", 5.0, maximum_use=1, used=1)
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "no longer valid"):
				self._apply(reference.cart_id, exhausted)

	def test_multiple_distinct_codes_are_rejected_atomically(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Only one promotion code"):
				self._apply(reference.cart_id, self.discount_code, self.other_code)
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.coupon_code)
		self.assertEqual(CartSerializer().serialize(reference, quotation)["promotions"], [])

	def test_second_distinct_code_while_one_applied_is_rejected(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._apply(reference.cart_id, self.discount_code)
			with self.assertRaisesRegex(InvalidDataError, "Only one promotion code"):
				self._apply(reference.cart_id, self.other_code)
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertEqual(
			quotation.coupon_code,
			frappe.db.get_value("Coupon Code", {"coupon_code": self.discount_code}, "name"),
		)
		self.assertAlmostEqual(
			CartSerializer().serialize(reference, quotation)["item_subtotal"],
			ITEM_PRICE * 0.9,
		)

	def test_remove_clears_coupon_and_recalculates_totals(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._apply(reference.cart_id, self.discount_code)
			self._remove(reference.cart_id, self.discount_code)
			reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertIsNone(quotation.coupon_code)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["promotions"], [])
		self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE)
		self.assertAlmostEqual(cart["items"][0]["unit_price"], ITEM_PRICE)

	def test_remove_rejects_code_that_is_not_applied(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._apply(reference.cart_id, self.discount_code)
			with self.assertRaisesRegex(InvalidDataError, "not applied"):
				self._remove(reference.cart_id, self.other_code)
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNotNone(quotation.coupon_code)

	def test_remove_on_cart_without_promotions_is_a_no_op(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._remove(reference.cart_id, self.discount_code)
			_reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.coupon_code)

	def test_create_with_promo_codes_applies_coupon(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart(
				items=[StoreAddCartLineItem(variant_id=self.masters.item, quantity=2)],
				promo_codes=[self.discount_code],
			)
		self.assertEqual(
			quotation.coupon_code,
			frappe.db.get_value("Coupon Code", {"coupon_code": self.discount_code}, "name"),
		)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["promotions"][0]["code"], self.discount_code)
		self.assertAlmostEqual(cart["item_subtotal"], 2 * ITEM_PRICE * 0.9)

	def test_create_with_multiple_codes_rejects_whole_cart(self) -> None:
		carts_before = frappe.db.count("Ceto Cart Reference")
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Only one promotion code"):
				self._create_cart(
					items=[StoreAddCartLineItem(variant_id=self.masters.item, quantity=1)],
					promo_codes=[self.discount_code, self.other_code],
				)
		frappe.db.rollback()  # simulate the request rollback that follows a failed create
		self.assertEqual(frappe.db.count("Ceto Cart Reference"), carts_before)

	def test_update_promo_codes_replaces_the_coupon(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		self.other_code = self._make_coupon("SAVE20", 20.0)
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.update(reference.cart_id, StoreUpdateCart(promo_codes=[self.discount_code]))
			reference, quotation = self.service.retrieve(reference.cart_id)
			self.assertEqual(
				quotation.coupon_code,
				frappe.db.get_value("Coupon Code", {"coupon_code": self.discount_code}, "name"),
			)
			self.service.update(reference.cart_id, StoreUpdateCart(promo_codes=[self.other_code]))
			reference, quotation = self.service.retrieve(reference.cart_id)
			self.assertEqual(
				quotation.coupon_code,
				frappe.db.get_value("Coupon Code", {"coupon_code": self.other_code}, "name"),
			)
			# Empty list clears the promotion.
			self.service.update(reference.cart_id, StoreUpdateCart(promo_codes=[]))
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.coupon_code)
		self.assertAlmostEqual(CartSerializer().serialize(reference, quotation)["item_subtotal"], ITEM_PRICE)

	def test_guard_rejection_prevents_promotion_mutation(self) -> None:
		from ceto.services.carts.line_items import CartLineItems

		reference, _quotation = self._create_cart_with_line()

		def reject(reference):
			raise NotAllowedError("Publishable API key cannot access this cart region")

		def no_save(*args, **kwargs):
			raise AssertionError("mutation attempted despite guard rejection")

		for mutate in (
			lambda: self.service.add_promotions(
				reference.cart_id,
				StoreCartAddPromotion(promo_codes=[self.discount_code]),
				guard=reject,
			),
			lambda: self.service.remove_promotions(
				reference.cart_id,
				StoreCartRemovePromotion(promo_codes=[self.discount_code]),
				guard=reject,
			),
		):
			with (
				self.subTest(mutate=mutate),
				self.assertRaisesRegex(NotAllowedError, "cannot access"),
				patch.object(CartLineItems, "save", no_save),
				patch("frappe.model.document.Document.save", no_save),
			):
				mutate()

	def test_promotion_mutations_lock_cart_and_quotation_first(self) -> None:
		reference, _quotation = self._create_cart_with_line()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			for mutate in (
				lambda: self._apply(reference.cart_id, self.discount_code),
				lambda: self._remove(reference.cart_id, self.discount_code),
			):
				with self.subTest(mutate=mutate):
					with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as database_sql:
						mutate()
						lock_queries = [
							" ".join(call.args[0].split())
							for call in database_sql.call_args_list
							if call.args and isinstance(call.args[0], str) and "FOR UPDATE" in call.args[0]
						]
						self.assertEqual(
							lock_queries[:2],
							[
								"SELECT name FROM `tabCeto Cart Reference` WHERE name = %s FOR UPDATE",
								"SELECT name FROM `tabQuotation` WHERE name = %s FOR UPDATE",
							],
						)
