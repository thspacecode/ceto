"""Phase 4 shipping tests: the applied rule charge on the cart.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. The Shipping Rule charge row, its amount and the
Quotation totals are produced by ERPNext; the tests only assert on the
serialized cart and on the state the apply service leaves behind (option
resolution, replacement charge-row handling, the country eligibility the
ERPNext controllers enforce on save).
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt, get_datetime

from ceto.routing.exceptions import InvalidDataError, NotAllowedError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.services.carts.shipping import CartShipping, CartShippingMethods
from ceto.tests.data.cart_test_data import (
	SHIPPING_COUNTRY_RATE_AMOUNT,
	SHIPPING_COUNTRY_RATE_LABEL,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	TAX_RATE,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreAddCartLineItem, StoreAddCartShippingMethods, StoreCreateCart

# Replacement across charge rows needs a rule posting to a different account
# than the shared shipping fixture account; the rule master is transaction
# scoped here (no router rollback to survive in service tests).
ALT_SHIPPING_ACCOUNT = "Ceto Service Test Alt Shipping Charges"
ALT_RATE_LABEL = "Ceto Service Test Alt Account Rate"
ALT_RATE_AMOUNT = 75.0


class TestCartShippingSerialization(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier module's committed cart (kept to survive a request
		# rollback — the completion suite commits placed orders) leaves its
		# guest-linked temporary Address behind; ERPNext would refill this
		# module's addressless carts from it and the country rule would
		# reject the inherited foreign address on the controller save.
		self.masters.discard_committed_cart_temporaries()
		self.service = CartService()

	def _create_cart_with_line(self) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _apply_rule(self, reference, rule: str) -> tuple:
		"""Link ``rule`` on the Quotation and let ERPNext apply the charge."""
		_reference, quotation = self.service.retrieve(reference.cart_id)
		quotation.shipping_rule = rule
		CartLineItems.save(quotation)
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.retrieve(reference.cart_id)

	def _line_id(self, reference) -> str:
		return frappe.get_all(
			"Ceto Cart Line Item Reference",
			filters={"cart_reference": reference.name},
			pluck="name",
		)[0]

	def test_cart_without_rule_reports_no_shipping(self) -> None:
		reference, quotation = self._create_cart_with_line()

		cart = CartSerializer().serialize(reference, quotation)

		self.assertEqual(cart["shipping_methods"], [])
		for field in (
			"shipping_total",
			"shipping_subtotal",
			"shipping_tax_total",
			"original_shipping_total",
			"original_shipping_subtotal",
			"original_shipping_tax_total",
		):
			self.assertEqual(cart[field], 0, field)

	def test_applied_rule_serializes_one_shipping_method(self) -> None:
		reference, quotation = self._create_cart_with_line()
		reference, quotation = self._apply_rule(reference, self.masters.flat_rate_rule)

		row = next(tax for tax in quotation.taxes if tax.charge_type == "Actual")
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(
			cart["shipping_methods"],
			[
				{
					"id": row.name,
					"cart_id": reference.cart_id,
					"shipping_option_id": self.masters.flat_rate_rule,
					"name": SHIPPING_FLAT_RATE_LABEL,
					"amount": SHIPPING_FLAT_RATE_AMOUNT,
					"subtotal": SHIPPING_FLAT_RATE_AMOUNT,
					"tax_total": 0,
					"total": SHIPPING_FLAT_RATE_AMOUNT,
					"is_tax_inclusive": False,
					"created_at": get_datetime(row.creation).isoformat(),
					"updated_at": get_datetime(row.modified).isoformat(),
				}
			],
		)
		self.assertEqual(cart["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(cart["shipping_subtotal"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(cart["shipping_tax_total"], 0)
		self.assertEqual(cart["original_shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(cart["original_shipping_subtotal"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(cart["original_shipping_tax_total"], 0)
		# The charge is part of ERPNext's own grand total, not added on top.
		self.assertAlmostEqual(cart["total"], flt(quotation.grand_total))

	def test_shipping_charge_is_a_charge_not_item_tax(self) -> None:
		reference, quotation = self._create_cart_with_line()
		reference, quotation = self._apply_rule(reference, self.masters.flat_rate_rule)

		cart = CartSerializer().serialize(reference, quotation)
		item_subtotal = flt(quotation.net_total)
		item_tax = TAX_RATE / 100 * item_subtotal

		# ERPNext folds the Actual charge row into total_taxes_and_charges
		# (and proportionally into every item tax allocation); the serializer
		# must carve it out of every tax field Medusa reads.
		self.assertAlmostEqual(
			cart["tax_total"], flt(quotation.total_taxes_and_charges) - SHIPPING_FLAT_RATE_AMOUNT
		)
		self.assertAlmostEqual(cart["tax_total"], item_tax)
		for field in ("item_tax_total", "original_item_tax_total", "original_tax_total"):
			self.assertAlmostEqual(cart[field], item_tax, msg=field)
		self.assertAlmostEqual(cart["item_total"], item_subtotal + item_tax)
		self.assertAlmostEqual(cart["original_item_total"], flt(quotation.total) + item_tax)
		self.assertAlmostEqual(sum(item["tax_total"] for item in cart["items"]), item_tax)
		# Medusa reconciles the subtotal from the item and shipping subtotals;
		# on ERPNext's own numbers the totals satisfy the pinned contract
		# total + discount_total == subtotal + tax_total (Ceto keeps the
		# document-level discount fields zeroed).
		self.assertAlmostEqual(cart["subtotal"], item_subtotal + SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(cart["original_subtotal"], flt(quotation.total) + SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(cart["total"], flt(quotation.grand_total))
		self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])
		self.assertAlmostEqual(cart["total"] + cart["discount_total"], cart["subtotal"] + cart["tax_total"])

	def test_switching_rule_updates_amount_and_option(self) -> None:
		reference, quotation = self._create_cart_with_line()
		reference, quotation = self._apply_rule(reference, self.masters.flat_rate_rule)

		reference, quotation = self._apply_rule(reference, self.masters.country_rate_rule)
		row = next(tax for tax in quotation.taxes if tax.charge_type == "Actual")
		method = CartSerializer().serialize(reference, quotation)["shipping_methods"][0]
		# ERPNext keeps one charge row per account/cost center and only
		# rewrites its amount, so the row identity survives the switch while
		# the option and name follow the newly linked rule.
		self.assertEqual(method["id"], row.name)
		self.assertEqual(method["shipping_option_id"], self.masters.country_rate_rule)
		self.assertEqual(method["name"], SHIPPING_COUNTRY_RATE_LABEL)
		self.assertEqual(method["amount"], SHIPPING_COUNTRY_RATE_AMOUNT)
		self.assertEqual(method["total"], SHIPPING_COUNTRY_RATE_AMOUNT)

	def test_rule_without_charge_row_reports_no_shipping(self) -> None:
		reference, quotation = self._create_cart_with_line()

		# Linked but never applied: ERPNext wrote no charge row yet.
		quotation.shipping_rule = self.masters.flat_rate_rule
		self.assertEqual(CartSerializer().serialize(reference, quotation)["shipping_methods"], [])

		# Linked master is gone: nothing identifies a charge to report.
		quotation.shipping_rule = "Missing Shipping Rule"
		self.assertEqual(CartSerializer().serialize(reference, quotation)["shipping_methods"], [])

	def test_itemless_cart_reports_zero_not_the_stale_charge(self) -> None:
		reference, quotation = self._create_cart_with_line()
		reference, quotation = self._apply_rule(reference, self.masters.flat_rate_rule)

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.delete_line_item(reference.cart_id, self._line_id(reference))
			reference, quotation = self.service.retrieve(reference.cart_id)

		# The empty-cart baseline zeroes the kept row's amount, so the method
		# stays listed with the ERPNext-derived 0 instead of the rule amount.
		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		method = CartSerializer().serialize(reference, quotation)["shipping_methods"][0]
		self.assertEqual(method["name"], SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(method["amount"], 0)
		self.assertEqual(method["total"], 0)

	def test_charge_row_prefers_the_labelled_row(self) -> None:
		reference, quotation = self._create_cart_with_line()
		reference, quotation = self._apply_rule(reference, self.masters.flat_rate_rule)

		quotation.append(
			"taxes",
			{
				"charge_type": "Actual",
				"account_head": self.masters.shipping_account,
				"cost_center": self.masters.shipping_cost_center,
				"description": "Mystery charge",
				"tax_amount": 999,
			},
		)
		charge = CartShipping.applied_charge(quotation)

		self.assertIsNotNone(charge)
		self.assertEqual(charge.rule, self.masters.flat_rate_rule)
		self.assertEqual(charge.label, SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(charge.tax_row.description, SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(charge.amount, SHIPPING_FLAT_RATE_AMOUNT)


class TestCartShippingMethods(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def _cart_with_line(self, **create_kwargs) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart(**create_kwargs))
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _apply(self, cart_id: str, option_id: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.set_shipping_method(cart_id, StoreAddCartShippingMethods(option_id=option_id))

	def _alt_rate_rule(self) -> str:
		"""Return a committed-label rule posting to its own shipping account."""
		abbr = frappe.db.get_value("Company", self.masters.company, "abbr")
		account = frappe.db.get_value(
			"Account", {"account_name": ALT_SHIPPING_ACCOUNT, "company": self.masters.company, "is_group": 0}
		)
		if not account:
			account = (
				frappe.get_doc(
					{
						"doctype": "Account",
						"account_name": ALT_SHIPPING_ACCOUNT,
						"parent_account": f"Direct Income - {abbr}",
						"company": self.masters.company,
						"is_group": 0,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		return self.masters.make_shipping_rule(
			ALT_RATE_LABEL, account=account, shipping_amount=ALT_RATE_AMOUNT
		)

	@staticmethod
	def _actual_rows(quotation) -> list:
		return [row for row in quotation.taxes or [] if row.charge_type == "Actual"]

	def test_applies_a_fixed_rule_through_erpnext(self) -> None:
		reference, quotation = self._cart_with_line()

		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)

		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertEqual(len(self._actual_rows(quotation)), 1)
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_FLAT_RATE_AMOUNT)

	def test_replacing_across_accounts_drops_the_previous_charge_row(self) -> None:
		alt_rule = self._alt_rate_rule()
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)

		reference, quotation = self._apply(reference.cart_id, alt_rule)

		# A different account cannot reuse the flat-rate row; without the
		# detach, ERPNext would append a second Actual row and count shipping
		# twice on the cart.
		rows = self._actual_rows(quotation)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].account_head, frappe.db.get_value("Shipping Rule", alt_rule, "account"))
		self.assertEqual(flt(rows[0].tax_amount), ALT_RATE_AMOUNT)
		item_tax = TAX_RATE / 100 * flt(quotation.net_total)
		self.assertAlmostEqual(
			flt(quotation.grand_total), flt(quotation.net_total) + item_tax + ALT_RATE_AMOUNT
		)

		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)

		rows = self._actual_rows(quotation)
		self.assertEqual(len(rows), 1)
		self.assertEqual(flt(rows[0].tax_amount), SHIPPING_FLAT_RATE_AMOUNT)

	def test_unknown_option_is_invalid_data_without_mutation(self) -> None:
		reference, quotation = self._cart_with_line()

		with self.assertRaisesRegex(InvalidDataError, "not found"):
			self._apply(reference.cart_id, "Ceto Missing Rule")

		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_disabled_option_is_invalid_data_without_mutation(self) -> None:
		reference, quotation = self._cart_with_line()

		with self.assertRaisesRegex(InvalidDataError, "disabled"):
			self._apply(reference.cart_id, self.masters.disabled_rate_rule)

		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_buying_rule_is_invalid_data(self) -> None:
		reference, quotation = self._cart_with_line()
		buying_rule = (
			frappe.get_doc(
				{
					"doctype": "Shipping Rule",
					"label": f"Ceto Service Test Buying Rate {self.masters.suffix}",
					"shipping_rule_type": "Buying",
					"company": self.masters.company,
					"account": self.masters.shipping_account,
					"cost_center": self.masters.shipping_cost_center,
					"calculate_based_on": "Fixed",
					"shipping_amount": SHIPPING_FLAT_RATE_AMOUNT,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		with self.assertRaisesRegex(InvalidDataError, "not available for carts"):
			self._apply(reference.cart_id, buying_rule)

		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_option_of_another_company_is_invalid_data(self) -> None:
		reference, quotation = self._cart_with_line()
		quotation.company = "Some Other Company"  # in-memory: the check compares the linked company

		with self.assertRaisesRegex(InvalidDataError, "cart's company"):
			CartShippingMethods.apply(quotation, self.masters.flat_rate_rule)

		reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_country_ineligible_option_is_invalid_data(self) -> None:
		# The country-rate rule is bound to the bootstrap country only; ERPNext
		# rejects it for a shipping address outside those countries on save.
		reference, quotation = self._cart_with_line(
			shipping_address={"country_code": "IN", "address_1": "1 Main Rd", "city": "Mumbai"}
		)

		with self.assertRaisesRegex(InvalidDataError, "not applicable for country"):
			self._apply(reference.cart_id, self.masters.country_rate_rule)

		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_country_eligible_option_applies(self) -> None:
		reference, quotation = self._cart_with_line(
			shipping_address={"country_code": "US", "address_1": "1 Main St", "city": "New York"}
		)

		reference, quotation = self._apply(reference.cart_id, self.masters.country_rate_rule)

		self.assertEqual(quotation.shipping_rule, self.masters.country_rate_rule)
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_COUNTRY_RATE_AMOUNT)

	def test_itemless_cart_keeps_the_option_without_a_charge(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())

		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)

		# ERPNext skips the totals calculation — and with it the rule
		# application — for itemless documents, so the option is stored but no
		# charge row exists to report.
		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertIsNone(CartShipping.applied_charge(quotation))
		self.assertEqual(CartSerializer().serialize(reference, quotation)["shipping_methods"], [])

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_FLAT_RATE_AMOUNT)

	def test_guard_rejection_prevents_shipping_mutation(self) -> None:
		reference, _quotation = self._cart_with_line()

		def reject(reference):
			raise NotAllowedError("Publishable API key cannot access this cart region")

		def no_save(*args, **kwargs):
			raise AssertionError("mutation attempted despite guard rejection")

		with (
			self.assertRaisesRegex(NotAllowedError, "cannot access"),
			patch.object(CartLineItems, "save", no_save),
			patch("frappe.model.document.Document.save", no_save),
		):
			self.service.set_shipping_method(
				reference.cart_id,
				StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule),
				guard=reject,
			)

	def test_shipping_mutation_locks_cart_and_quotation_first(self) -> None:
		reference, _quotation = self._cart_with_line()

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with patch.object(CartAccess, "_lock_row", side_effect=CartAccess._lock_row) as lock_row:
				self.service.set_shipping_method(
					reference.cart_id,
					StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule),
				)
		self.assertEqual(
			[locked.args for locked in lock_row.call_args_list][:2],
			[
				("Ceto Cart Reference", reference.cart_id),
				("Quotation", reference.quotation),
			],
		)
