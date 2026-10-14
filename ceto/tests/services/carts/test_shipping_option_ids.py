"""Phase 4 cart round-trip slice: opaque option ids on the apply surface.

The shipping-options surface serves every cart option under its opaque
``so_`` id; the cart apply accepts those tokens beside the legacy raw
``Shipping Rule`` names. Runs against real ERPNext controllers on the
test site inside a single rolled-back transaction: a built-in token
decodes to its rule and applies exactly like the raw name — same linked
rule, same charge row, amount and label — a malformed or
foreign-provider token is ``UNKNOWN_OPTION`` without any mutation, and
the applied method echoes the supplied id back only while it still
names the linked rule.
"""

from unittest.mock import patch

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.services.carts.shipping import UNKNOWN_OPTION, CartShipping
from ceto.services.shipping.ids import encode_option_id
from ceto.services.shipping.providers.erpnext import PROVIDER_ID
from ceto.tests.data.cart_test_data import (
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
	CartTestData,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreAddCartLineItem, StoreAddCartShippingMethods, StoreCreateCart


class TestOpaqueShippingOptionApply(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def _flat_option_id(self) -> str:
		return encode_option_id(PROVIDER_ID, self.masters.flat_rate_rule)

	def _cart_with_line(self) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.service.create(StoreCreateCart())
			self.service.add_line_item(
				reference.cart_id,
				StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
			)
			return self.service.retrieve(reference.cart_id)

	def _apply(self, cart_id: str, option_id: str) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.set_shipping_method(cart_id, StoreAddCartShippingMethods(option_id=option_id))

	def _applied_method(self, reference, quotation) -> dict:
		methods = CartSerializer().serialize(reference, quotation)["shipping_methods"]
		self.assertEqual(len(methods), 1)
		return methods[0]

	def _actual_rows(self, quotation) -> list:
		return [row for row in quotation.taxes or [] if row.charge_type == "Actual"]

	def test_opaque_id_applies_the_same_rule_as_the_raw_name(self) -> None:
		reference, quotation = self._cart_with_line()

		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertEqual(reference.shipping_option_id, self._flat_option_id())
		# The charge is ERPNext's own: the listed amount, applied unchanged.
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_FLAT_RATE_AMOUNT)

	def test_legacy_raw_rule_name_still_applies(self) -> None:
		reference, quotation = self._cart_with_line()

		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)

		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertEqual(reference.shipping_option_id, self.masters.flat_rate_rule)
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_FLAT_RATE_AMOUNT)

	def test_serialized_method_echoes_the_opaque_id_with_parity(self) -> None:
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		method = self._applied_method(reference, quotation)

		self.assertEqual(method["shipping_option_id"], self._flat_option_id())
		self.assertEqual(method["name"], SHIPPING_FLAT_RATE_LABEL)
		self.assertEqual(method["amount"], SHIPPING_FLAT_RATE_AMOUNT)
		self.assertEqual(method["total"], SHIPPING_FLAT_RATE_AMOUNT)

	def test_serialized_echo_follows_the_last_supplied_id_form(self) -> None:
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self.masters.flat_rate_rule)
		self.assertEqual(
			self._applied_method(reference, quotation)["shipping_option_id"], self.masters.flat_rate_rule
		)

		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		# The same rule re-applied through the opaque id: the record follows
		# the last supplied id while the charge row stays exactly one.
		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertEqual(len(self._actual_rows(quotation)), 1)
		self.assertEqual(
			self._applied_method(reference, quotation)["shipping_option_id"], self._flat_option_id()
		)

	def test_serialized_echo_falls_back_to_the_rule_name_without_a_record(self) -> None:
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		# A cart predating the record carries no supplied id: the method
		# keeps serving the raw rule name instead of inventing a token.
		reference.shipping_option_id = None
		self.assertEqual(
			self._applied_method(reference, quotation)["shipping_option_id"], self.masters.flat_rate_rule
		)

	def test_serialized_echo_falls_back_when_the_record_names_another_rule(self) -> None:
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		# A stale record for a different rule must not masquerade as the
		# linked method: the echo falls back to the raw rule name.
		reference.shipping_option_id = encode_option_id(PROVIDER_ID, self.masters.country_rate_rule)
		self.assertEqual(
			self._applied_method(reference, quotation)["shipping_option_id"], self.masters.flat_rate_rule
		)

	def test_serialized_echo_falls_back_for_foreign_and_malformed_records(self) -> None:
		reference, quotation = self._cart_with_line()
		reference, quotation = self._apply(reference.cart_id, self._flat_option_id())

		for record in ("so_###", encode_option_id("ups", self.masters.flat_rate_rule)):
			with self.subTest(record=record):
				reference.shipping_option_id = record
				self.assertEqual(
					self._applied_method(reference, quotation)["shipping_option_id"],
					self.masters.flat_rate_rule,
				)

	def test_malformed_token_is_unknown_option_without_mutation(self) -> None:
		reference, quotation = self._cart_with_line()

		with self.assertRaisesRegex(InvalidDataError, UNKNOWN_OPTION):
			self._apply(reference.cart_id, "so_###")

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])
		self.assertIsNone(reference.shipping_option_id)

	def test_foreign_provider_token_is_unknown_option_without_mutation(self) -> None:
		reference, quotation = self._cart_with_line()

		with self.assertRaisesRegex(InvalidDataError, UNKNOWN_OPTION):
			self._apply(reference.cart_id, encode_option_id("ups", self.masters.flat_rate_rule))

		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_well_formed_token_of_an_unknown_rule_is_unknown_option(self) -> None:
		reference, quotation = self._cart_with_line()

		with self.assertRaisesRegex(InvalidDataError, UNKNOWN_OPTION):
			self._apply(reference.cart_id, encode_option_id(PROVIDER_ID, "Ceto Missing Rule"))

		self.assertIsNone(quotation.shipping_rule)
		self.assertEqual(self._actual_rows(quotation), [])

	def test_reapplying_the_same_opaque_id_skips_the_reference_write(self) -> None:
		reference, quotation = self._cart_with_line()
		option_id = self._flat_option_id()
		reference, quotation = self._apply(reference.cart_id, option_id)

		original_save = frappe.model.document.Document.save
		saved_references: list[str] = []

		def recording_save(doc, *args, **kwargs):
			if doc.doctype == "Ceto Cart Reference":
				saved_references.append(doc.name)
			return original_save(doc, *args, **kwargs)

		with patch("frappe.model.document.Document.save", recording_save):
			reference, quotation = self._apply(reference.cart_id, option_id)

		# An unchanged record is never written back: the re-apply still
		# persists the Quotation (the charge row), just not the reference.
		self.assertEqual(saved_references, [])
		self.assertEqual(reference.shipping_option_id, option_id)
		self.assertEqual(quotation.shipping_rule, self.masters.flat_rate_rule)
		self.assertEqual(len(self._actual_rows(quotation)), 1)
		self.assertEqual(CartShipping.applied_charge(quotation).amount, SHIPPING_FLAT_RATE_AMOUNT)
