"""Phase 4 cart-taxes service tests: explicit recalculation and template refresh.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. Tax rates, Shipping Rule charges and every total are
produced by ERPNext; the tests only assert on the resulting documents and the
serialized cart.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import InvalidDataError, NotAllowedError
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import (
	ALT_TAX_RATE,
	ALT_TEST_TAX_ACCOUNT,
	ITEM_PRICE,
	SHIPPING_FLAT_RATE_AMOUNT,
	TAX_RATE,
	TEST_TAX_ACCOUNT,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCreateCart,
	StoreUpdateCart,
)


class TestCartTaxesRecalculation(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def _cart_with_line(self) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _apply_flat_rule(self, cart_id: str) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.service.set_shipping_method(
				cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)

	def _calculate(self, cart_id: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.calculate_taxes(cart_id)

	@staticmethod
	def _actual_rows(quotation) -> list:
		return quotation.get("taxes", filters={"charge_type": "Actual"}) or []

	def test_recalculate_is_idempotent(self) -> None:
		reference, _quotation = self._cart_with_line()
		self._apply_flat_rule(reference.cart_id)
		first_reference, quotation = self._calculate(reference.cart_id)
		first = CartSerializer().serialize(first_reference, quotation)
		tax_row_names = [row.name for row in quotation.get("taxes")]

		second_reference, quotation = self._calculate(reference.cart_id)
		second = CartSerializer().serialize(second_reference, quotation)

		for field in ("subtotal", "tax_total", "shipping_total", "total"):
			self.assertAlmostEqual(second[field], first[field], msg=field)
		# No charge or template row is duplicated by a repeated recalculation.
		self.assertEqual(len(self._actual_rows(quotation)), 1)
		self.assertEqual([row.name for row in quotation.get("taxes")], tax_row_names)
		self.assertAlmostEqual(second["total"], second["subtotal"] + second["tax_total"])

	def test_recalculate_rebuilds_totals_through_erpnext(self) -> None:
		reference, quotation = self._cart_with_line()
		self._apply_flat_rule(reference.cart_id)
		# Drift the stored summary away from the rows, as a previous bug or a
		# direct write could have; the recalculation must restore ERPNext's
		# own numbers instead of trusting them.
		frappe.db.set_value(
			"Quotation",
			quotation.name,
			{"net_total": 999, "total_taxes_and_charges": 999, "grand_total": 999},
			update_modified=False,
		)

		reference, quotation = self._calculate(reference.cart_id)

		cart = CartSerializer().serialize(reference, quotation)
		self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE)
		self.assertAlmostEqual(cart["tax_total"], TAX_RATE / 100 * ITEM_PRICE)
		self.assertAlmostEqual(cart["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)
		expected_total = ITEM_PRICE * (1 + TAX_RATE / 100) + SHIPPING_FLAT_RATE_AMOUNT
		self.assertAlmostEqual(cart["total"], expected_total)

	def test_recalculate_keeps_empty_cart_baseline(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())

		reference, quotation = self._calculate(reference.cart_id)

		cart = CartSerializer().serialize(reference, quotation)
		for field in ("total", "subtotal", "tax_total", "shipping_total"):
			self.assertEqual(cart[field], 0, field)
		self.assertEqual(cart["items"], [])

	def test_guard_rejection_prevents_recalculation(self) -> None:
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
			self.service.calculate_taxes(reference.cart_id, guard=reject)

	def test_recalculation_locks_cart_and_quotation_first(self) -> None:
		reference, _quotation = self._cart_with_line()

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as database_sql:
				self.service.calculate_taxes(reference.cart_id)
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


class TestCartTemplateRefresh(CetoTestSuite):
	"""Region/sales-channel changes that move ``taxes_and_charges``."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def _configuration(self) -> dict:
		return {
			**self.masters.configuration,
			"regions": {
				"reg_test": {},
				"reg_alt": {"taxes_and_charges": self.masters.alt_taxes_and_charges},
			},
		}

	def _cart_with_line(self, configuration: dict) -> tuple:
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _update(self, cart_id: str, configuration: dict, **payload) -> tuple:
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			return self.service.update(cart_id, StoreUpdateCart(**payload))

	def _template_accounts(self, template: str) -> list[str]:
		return frappe.get_all(
			"Sales Taxes and Charges",
			filters={"parenttype": "Sales Taxes and Charges Template", "parent": template},
			pluck="account_head",
		)

	def test_template_change_reloads_rows_from_erpnext(self) -> None:
		configuration = self._configuration()
		reference, _quotation = self._cart_with_line(configuration)

		reference, quotation = self._update(reference.cart_id, configuration, region_id="reg_alt")

		# The 10% template rows are replaced by the 5% template's own rows;
		# keeping the old link-only switch would price the cart with stale
		# rates.
		self.assertEqual(quotation.taxes_and_charges, self.masters.alt_taxes_and_charges)
		self.assertEqual(
			[row.account_head for row in quotation.get("taxes")],
			self._template_accounts(self.masters.alt_taxes_and_charges),
		)
		self.assertNotIn(TEST_TAX_ACCOUNT, [row.description for row in quotation.get("taxes")])
		cart = CartSerializer().serialize(reference, quotation)
		self.assertAlmostEqual(cart["tax_total"], ALT_TAX_RATE / 100 * ITEM_PRICE)
		self.assertAlmostEqual(cart["total"], ITEM_PRICE * (1 + ALT_TAX_RATE / 100))

	def test_template_change_preserves_the_selected_shipping_exactly_once(self) -> None:
		configuration = self._configuration()
		reference, _quotation = self._cart_with_line(configuration)
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			self.service.set_shipping_method(
				reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)

		reference, quotation = self._update(reference.cart_id, configuration, region_id="reg_alt")

		# The charge row lived inside the replaced taxes table; the preserved
		# rule link makes the controller save recreate exactly one charge.
		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		actual = [row for row in quotation.get("taxes") if row.charge_type == "Actual"]
		self.assertEqual(len(actual), 1)
		self.assertEqual(flt(actual[0].tax_amount), SHIPPING_FLAT_RATE_AMOUNT)

		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(len(cart["shipping_methods"]), 1)
		self.assertEqual(cart["shipping_methods"][0]["shipping_option_id"], self.masters.flat_rate_rule)
		self.assertEqual(cart["shipping_methods"][0]["amount"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(cart["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)
		expected_total = ITEM_PRICE * (1 + ALT_TAX_RATE / 100) + SHIPPING_FLAT_RATE_AMOUNT
		self.assertAlmostEqual(cart["total"], expected_total)
		self.assertAlmostEqual(cart["total"], cart["subtotal"] + cart["tax_total"])

	def test_same_template_keeps_rows_untouched(self) -> None:
		configuration = {
			**self._configuration(),
			"sales_channels": {"sc_test": {}, "sc_other": {}},
		}
		reference, quotation = self._cart_with_line(configuration)
		row_names = [row.name for row in quotation.get("taxes")]

		reference, quotation = self._update(reference.cart_id, configuration, sales_channel_id="sc_other")
		self.assertEqual([row.name for row in quotation.get("taxes")], row_names)
		self.assertEqual(quotation.taxes_and_charges, self.masters.taxes_and_charges)

		# Re-submitting the same region is equally churn-free.
		reference, quotation = self._update(reference.cart_id, configuration, region_id="reg_test")
		self.assertEqual([row.name for row in quotation.get("taxes")], row_names)

	def test_missing_template_is_invalid_data_without_mutation(self) -> None:
		configuration = {
			**self.masters.configuration,
			"regions": {"reg_test": {}, "reg_bad": {"taxes_and_charges": "Ceto Missing Template"}},
		}
		reference, quotation = self._cart_with_line(configuration)
		row_names = [row.name for row in quotation.get("taxes")]

		with self.assertRaisesRegex(InvalidDataError, "not found"):
			self._update(reference.cart_id, configuration, region_id="reg_bad")

		reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertEqual(reference.region_id, "reg_test")
		self.assertEqual(quotation.taxes_and_charges, self.masters.taxes_and_charges)
		self.assertEqual([row.name for row in quotation.get("taxes")], row_names)

	def test_disabled_template_is_invalid_data_without_mutation(self) -> None:
		configuration = self._configuration()
		reference, quotation = self._cart_with_line(configuration)
		row_names = [row.name for row in quotation.get("taxes")]
		template = frappe.get_doc("Sales Taxes and Charges Template", self.masters.alt_taxes_and_charges)
		template.disabled = 1
		template.save(ignore_permissions=True)
		frappe.clear_document_cache("Sales Taxes and Charges Template", template.name)

		with self.assertRaisesRegex(InvalidDataError, "disabled"):
			self._update(reference.cart_id, configuration, region_id="reg_alt")

		reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertEqual(reference.region_id, "reg_test")
		self.assertEqual(quotation.taxes_and_charges, self.masters.taxes_and_charges)
		self.assertEqual([row.name for row in quotation.get("taxes")], row_names)

	def test_disabled_template_matches_erpnext_message(self) -> None:
		configuration = self._configuration()
		reference, _quotation = self._cart_with_line(configuration)
		template = frappe.get_doc("Sales Taxes and Charges Template", self.masters.alt_taxes_and_charges)
		template.disabled = 1
		template.save(ignore_permissions=True)
		frappe.clear_document_cache("Sales Taxes and Charges Template", template.name)

		# The eager rejection carries the same wording the ERPNext controllers
		# use on save, so either path reads the same to the storefront.
		with self.assertRaisesRegex(InvalidDataError, f"'{self.masters.alt_taxes_and_charges}' is disabled"):
			self._update(reference.cart_id, configuration, region_id="reg_alt")


class TestCartTaxesErrorMapping(CetoTestSuite):
	"""Controller validation on the shared save maps through the router."""

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def test_missing_template_error_is_invalid_data(self) -> None:
		# The router maps a bare frappe DoesNotExistError to a 404, which
		# would mask the cart itself as not found; the loader must raise
		# invalid_data instead.
		from types import SimpleNamespace

		from ceto.services.carts.taxes import CartTaxes

		quotation = SimpleNamespace(taxes_and_charges=self.masters.taxes_and_charges)
		with self.assertRaisesRegex(InvalidDataError, "not found"):
			CartTaxes.refresh_template(quotation, "Ceto Missing Template")
