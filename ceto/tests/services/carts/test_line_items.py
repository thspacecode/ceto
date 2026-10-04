"""Phase 2 line-item service tests: pricing, totals, mappings and locking.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. Item Price resolution, taxes and Quotation totals are
produced by ERPNext; the tests only assert on the resulting documents.
"""

from unittest.mock import patch

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.line_items import CartLineItems
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import ITEM_PRICE, ITEM_PRICE_B, CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCreateCart,
	StoreLineItemDeleteResponse,
	StoreUpdateCart,
	StoreUpdateCartLineItem,
)


class TestCartLineItems(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.service = CartService()

	def _create_cart(self, **payload) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			return self.service.create(StoreCreateCart(**payload))

	def _add_line(self, cart_id: str, quantity: int = 2, metadata=None, variant=None) -> str:
		_reference, _quotation, mapping = self.service.add_line_item(
			cart_id,
			StoreAddCartLineItem(
				variant_id=variant or self.masters.item, quantity=quantity, metadata=metadata
			),
		)
		return mapping.line_id

	def test_add_resolves_price_from_item_price(self) -> None:
		reference, _quotation = self._create_cart(email="lines@example.com")
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id)
			reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertRegex(line_id, r"^li_[0-9a-f]{32}$")
		row = quotation.items[-1]
		self.assertEqual(row.item_code, self.masters.item)
		self.assertEqual(row.qty, 2)
		self.assertEqual(row.rate, ITEM_PRICE)
		self.assertEqual(row.price_list_rate, ITEM_PRICE)
		mapping = frappe.get_doc("Ceto Cart Line Item Reference", line_id)
		self.assertEqual(mapping.quotation_item, row.name)
		self.assertEqual(mapping.cart_reference, reference.name)
		self.assertIsNone(mapping.metadata)

	def test_add_serializes_mapped_line_in_quotation_order(self) -> None:
		reference, _quotation = self._create_cart(metadata={"cart": True})
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			first = self._add_line(reference.cart_id, quantity=1, metadata={"slot": 1})
			second = self._add_line(
				reference.cart_id, quantity=3, metadata={"slot": 2}, variant=self.masters.other_item
			)
			reference, quotation = self.service.retrieve(reference.cart_id)

		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual([item["id"] for item in cart["items"]], [first, second])
		item = cart["items"][0]
		self.assertEqual(item["cart_id"], reference.cart_id)
		self.assertEqual(item["title"], frappe.db.get_value("Item", self.masters.item, "item_name"))
		self.assertEqual(item["variant_id"], self.masters.item)
		self.assertEqual(item["quantity"], 1)
		self.assertEqual(item["unit_price"], ITEM_PRICE)
		self.assertEqual(item["original_unit_price"], ITEM_PRICE)
		self.assertEqual(item["metadata"], {"slot": 1})
		self.assertAlmostEqual(item["subtotal"], ITEM_PRICE)
		# Per-line tax comes from ERPNext's own item-wise tax calculation.
		self.assertAlmostEqual(item["tax_total"], 0.1 * ITEM_PRICE)
		self.assertAlmostEqual(item["total"], 1.1 * ITEM_PRICE)

	def test_line_taxes_reconcile_with_cart_totals(self) -> None:
		"""Sum of line tax/line totals equals the cart item tax/item totals."""
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._add_line(reference.cart_id, quantity=2)
			self._add_line(reference.cart_id, quantity=3, variant=self.masters.other_item)
			reference, quotation = self.service.retrieve(reference.cart_id)

		cart = CartSerializer().serialize(reference, quotation)
		net_total = ITEM_PRICE * 2 + ITEM_PRICE_B * 3
		self.assertAlmostEqual(cart["item_subtotal"], net_total)
		self.assertAlmostEqual(cart["item_tax_total"], 0.1 * net_total)
		self.assertAlmostEqual(
			sum(item["tax_total"] for item in cart["items"]), cart["item_tax_total"], places=2
		)
		self.assertAlmostEqual(sum(item["total"] for item in cart["items"]), cart["item_total"], places=2)

	def test_add_merges_quantity_for_existing_variant(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id, quantity=1, metadata={"gift": True})
			merged_id = self._add_line(reference.cart_id, quantity=2)
			reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertEqual(merged_id, line_id)
		self.assertEqual(len(quotation.items), 1)
		self.assertEqual(quotation.items[0].qty, 3)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(len(cart["items"]), 1)
		self.assertEqual(cart["items"][0]["metadata"], {"gift": True})

	def test_update_quantity_recalculates_erpnext_totals(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id, quantity=1)
			self.service.update_line_item(reference.cart_id, line_id, StoreUpdateCartLineItem(quantity=3))
			reference, quotation = self.service.retrieve(reference.cart_id)

		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(quotation.items[0].qty, 3)
		self.assertAlmostEqual(cart["item_subtotal"], 3 * ITEM_PRICE)
		self.assertAlmostEqual(cart["tax_total"], 0.3 * ITEM_PRICE)
		self.assertAlmostEqual(cart["total"], 3.3 * ITEM_PRICE)
		self.assertAlmostEqual(cart["items"][0]["subtotal"], 3 * ITEM_PRICE)

	def test_metadata_merge_semantics_match_cart_metadata(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id, metadata={"gift": True, "note": "hi"})

			self.service.update_line_item(
				reference.cart_id,
				line_id,
				StoreUpdateCartLineItem(quantity=1, metadata={"gift": None, "new": 2}),
			)
			reference, quotation = self.service.retrieve(reference.cart_id)
			self.assertEqual(
				CartSerializer().serialize(reference, quotation)["items"][0]["metadata"],
				{"note": "hi", "new": 2},
			)

			self.service.update_line_item(
				reference.cart_id, line_id, StoreUpdateCartLineItem(quantity=1, metadata=None)
			)
			reference, quotation = self.service.retrieve(reference.cart_id)
			self.assertEqual(CartSerializer().serialize(reference, quotation)["items"][0]["metadata"], None)

	def test_delete_removes_row_mapping_and_updates_totals(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id, quantity=2)
			_reference, _quotation, mapping = self.service.delete_line_item(reference.cart_id, line_id)
			reference, quotation = self.service.retrieve(reference.cart_id)

		self.assertEqual(mapping.line_id, line_id)
		self.assertEqual(quotation.items, [])
		self.assertFalse(frappe.db.exists("Ceto Cart Line Item Reference", line_id))
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["items"], [])
		self.assertEqual(cart["item_subtotal"], 0)
		self.assertEqual(cart["tax_total"], 0)
		self.assertEqual(cart["total"], 0)
		response = StoreLineItemDeleteResponse(id=line_id, parent=reference.cart_id)
		self.assertEqual(
			response.model_dump(),
			{"id": line_id, "object": "line-item", "deleted": True, "parent": reference.cart_id},
		)
		# The emptied cart survives and stays mutable.
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self._add_line(reference.cart_id, quantity=1)

	def test_create_with_items_builds_lines_in_initial_transaction(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self.service.create(
				StoreCreateCart(
					items=[
						StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
						StoreAddCartLineItem(
							variant_id=self.masters.other_item, quantity=2, metadata={"gift": True}
						),
					]
				)
			)
		self.assertEqual(len(quotation.items), 2)
		mappings = frappe.get_all(
			"Ceto Cart Line Item Reference",
			filters={"cart_reference": reference.name},
			pluck="line_id",
			order_by="creation",
		)
		self.assertEqual(len(mappings), 2)
		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual([item["id"] for item in cart["items"]], mappings)
		self.assertAlmostEqual(cart["item_subtotal"], ITEM_PRICE + 2 * ITEM_PRICE_B)
		self.assertAlmostEqual(cart["total"], 1.1 * (ITEM_PRICE + 2 * ITEM_PRICE_B))

	def test_create_with_failing_item_leaves_no_partial_references(self) -> None:
		def snapshot() -> tuple[int, int]:
			return (
				frappe.db.count("Ceto Cart Reference"),
				frappe.db.count("Ceto Cart Line Item Reference"),
			)

		before = snapshot()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Unknown variant id"):
				self.service.create(
					StoreCreateCart(
						items=[
							StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
							StoreAddCartLineItem(variant_id="no-such-item", quantity=1),
						]
					)
				)
		frappe.db.rollback()  # simulate the request rollback that follows a failed create
		self.assertEqual(snapshot(), before)

	def test_unknown_and_foreign_lines_are_masked(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			other_reference, _other = self._create_cart()
			foreign_line = self._add_line(other_reference.cart_id)

			for method in (
				lambda: self.service.update_line_item(
					reference.cart_id, "li_" + "0" * 32, StoreUpdateCartLineItem(quantity=1)
				),
				lambda: self.service.delete_line_item(reference.cart_id, "li_" + "0" * 32),
				lambda: self.service.update_line_item(
					reference.cart_id, foreign_line, StoreUpdateCartLineItem(quantity=1)
				),
				lambda: self.service.delete_line_item(reference.cart_id, foreign_line),
			):
				with (
					self.subTest(method=method),
					self.assertRaisesRegex(RouteNotFoundError, "Line item not found"),
				):
					method()
		self.assertTrue(frappe.db.exists("Ceto Cart Line Item Reference", foreign_line))

	def test_guard_rejection_prevents_any_mutation(self) -> None:
		"""A rejecting guard aborts before any save is attempted (no TOCTOU)."""
		from ceto.routing.exceptions import NotAllowedError

		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id, quantity=1)

			def reject(reference):
				raise NotAllowedError("Publishable API key cannot access this cart region")

			def no_save(*args, **kwargs):
				raise AssertionError("mutation attempted despite guard rejection")

			for mutate in (
				lambda: self.service.add_line_item(
					reference.cart_id,
					StoreAddCartLineItem(variant_id=self.masters.item, quantity=5),
					guard=reject,
				),
				lambda: self.service.update_line_item(
					reference.cart_id,
					line_id,
					StoreUpdateCartLineItem(quantity=9),
					guard=reject,
				),
				lambda: self.service.delete_line_item(reference.cart_id, line_id, guard=reject),
				lambda: self.service.update(
					reference.cart_id, StoreUpdateCart(email="attacker@example.com"), guard=reject
				),
			):
				with (
					self.subTest(mutate=mutate),
					self.assertRaisesRegex(NotAllowedError, "cannot access"),
					patch.object(CartLineItems, "save", no_save),
					patch("frappe.model.document.Document.save", no_save),
					patch("frappe.model.document.Document.insert", no_save),
					patch("frappe.model.document.Document.remove", no_save),
					patch("frappe.delete_doc", no_save),
				):
					mutate()

	def test_unknown_variant_is_rejected(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Unknown variant id"):
				self.service.add_line_item(
					reference.cart_id,
					StoreAddCartLineItem(variant_id="DEV-MISSING-001", quantity=1),
				)
			reference, quotation = self.service.retrieve(reference.cart_id)
		self.assertEqual(quotation.items, [])
		self.assertEqual(
			frappe.db.count("Ceto Cart Line Item Reference", {"cart_reference": reference.name}),
			0,
		)

	def test_mutations_lock_cart_and_quotation_first(self) -> None:
		reference, _quotation = self._create_cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			line_id = self._add_line(reference.cart_id)

			for mutate in (
				lambda: self.service.add_line_item(
					reference.cart_id,
					StoreAddCartLineItem(variant_id=self.masters.item, quantity=1),
				),
				lambda: self.service.update_line_item(
					reference.cart_id, line_id, StoreUpdateCartLineItem(quantity=5)
				),
				lambda: self.service.delete_line_item(reference.cart_id, line_id),
			):
				with self.subTest(mutate=mutate):
					with patch.object(CartAccess, "_lock_row", side_effect=CartAccess._lock_row) as lock_row:
						mutate()
					self.assertEqual(
						[locked.args for locked in lock_row.call_args_list][:2],
						[
							("Ceto Cart Reference", reference.cart_id),
							("Quotation", reference.quotation),
						],
					)
