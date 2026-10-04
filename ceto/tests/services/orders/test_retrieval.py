"""Phase 2 order retrieval: the pinned ``StoreOrder`` served by the service.

Focused retrieval view over the slice: ``OrderService.retrieve`` delegates
the canonical representation to the existing ``OrderSerializer`` and applies
the shared entity-neutral ``fields`` selector — and the served order is
byte-identical to the one the completion response placed, with the effective
owner served through the snapshot-first fallback and the Sales Order's
internal identity never surfacing (orders Recorded Decisions 1-4). The
tests complete real carts through the service on the test site inside a
single rolled-back transaction.
"""

import json

import frappe
from frappe.utils import flt

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.service import OrderService
from ceto.tests.data.cart_test_data import (
	ITEM_PRICE,
	SHIPPING_FLAT_RATE_AMOUNT,
	TAX_RATE,
	CartTestData,
	make_customer_with_user,
)
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCartAddressPayload,
	StoreCompleteCart,
	StoreCreateCart,
	StoreUpdateCart,
)

CART_TOTAL = flt(ITEM_PRICE * (1 + TAX_RATE / 100) + SHIPPING_FLAT_RATE_AMOUNT)


class TestOrderRetrieval(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.orders = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		# Frappe throttles user creation per hour; the ownership cases
		# create one user per run.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _cart(self, *, email: str = "guest@example.com") -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.carts.create(StoreCreateCart(email=email))
			self.carts.add_line_item(
				reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.item, quantity=1)
			)
			self.carts.update(
				reference.cart_id,
				StoreUpdateCart(
					shipping_address=StoreCartAddressPayload(
						address_1="1 Retrieval Way", city="Bangkok", country_code="th"
					)
				),
			)
			self.carts.set_shipping_method(
				reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)
			return self.carts.retrieve(reference.cart_id)

	def _complete(self, reference, *, user: str = "Guest"):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(user):
			return self.completion.complete(reference.cart_id, StoreCompleteCart())

	def _claim(self, reference, email: str) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			CartClaim().claim(reference.cart_id)

	def _order_reference(self, cart_id: str):
		return frappe.get_doc(
			"Ceto Order Reference", frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name")
		)

	def test_serves_the_pinned_order_of_a_placed_cart(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_reference = self._order_reference(reference.cart_id)

		order = self.orders.retrieve(order_reference.order_id, self.key)

		self.assertEqual(order["id"], order_reference.order_id)
		# A guest order has no owner: the unguessable id is its capability.
		self.assertIsNone(order["customer_id"])
		self.assertEqual(order["status"], "pending")
		self.assertEqual(order["payment_status"], "not_paid")
		self.assertEqual(order["fulfillment_status"], "not_fulfilled")
		# Region and sales channel come from the completed cart's reference.
		self.assertEqual(order["region_id"], "reg_test")
		self.assertEqual(order["sales_channel_id"], "sc_test")
		self.assertEqual(order["email"], "guest@example.com")
		self.assertAlmostEqual(order["total"], CART_TOTAL)
		# The internal lineage stays internal (Recorded Decision 1).
		self.assertNotIn("sales_order", order)

	def test_retrieval_matches_the_completion_order_byte_for_byte(self) -> None:
		email, customer = make_customer_with_user("retrieve")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		response = self._complete(reference, user=email)
		order_id = response.order.id
		self.assertEqual(response.order.customer_id, customer)

		# The same order for the owner and for any other holder of the id.
		for user in (email, "Guest"):
			with self.set_user(user):
				order = self.orders.retrieve(order_id, self.key)
			self.assertEqual(
				json.dumps(order, sort_keys=True),
				json.dumps(response.order.model_dump(mode="json"), sort_keys=True),
			)

	def test_serves_the_effective_owner_snapshot_first_with_the_cart_fallback(self) -> None:
		email, customer = make_customer_with_user("owner")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		self._complete(reference, user=email)
		order_reference = self._order_reference(reference.cart_id)

		order = self.orders.retrieve(order_reference.order_id, self.key)
		self.assertEqual(order["customer_id"], customer)

		# The Phase 6 legacy shape (no snapshot) falls back to the completed
		# cart's owner — the served customer_id is unchanged.
		frappe.db.set_value(
			"Ceto Order Reference", order_reference.name, "owner_customer", None, update_modified=False
		)
		order = self.orders.retrieve(order_reference.order_id, self.key)
		self.assertEqual(order["customer_id"], customer)

		# The Sales Order's own customer links are never ownership evidence.
		frappe.db.set_value("Sales Order", order_reference.sales_order, "customer", self.masters.customer)
		order = self.orders.retrieve(order_reference.order_id, self.key)
		self.assertEqual(order["customer_id"], customer)

	def test_the_sales_order_identity_never_surfaces(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_reference = self._order_reference(reference.cart_id)
		cart_reference = frappe.get_doc("Ceto Cart Reference", reference.cart_id)

		order = self.orders.retrieve(order_reference.order_id, self.key)

		rendered = json.dumps(order)
		# The public id is the order's identity; the Sales Order's name and
		# the lineage's Quotation name are internal and appear nowhere.
		self.assertIn(order_reference.order_id, rendered)
		self.assertNotIn(order_reference.sales_order, rendered)
		self.assertNotIn(cart_reference.quotation, rendered)

	def test_the_fields_selector_narrows_extends_and_fails_closed(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_id = self._order_reference(reference.cart_id).order_id
		full = self.orders.retrieve(order_id, self.key)

		narrowed = self.orders.retrieve(order_id, self.key, fields="id,status,total")
		self.assertEqual(set(narrowed), {"id", "status", "total"})
		self.assertEqual(narrowed["total"], full["total"])

		extended = self.orders.retrieve(order_id, self.key, fields="id,+total")
		self.assertEqual(set(extended), {"id", "total"})

		trimmed = self.orders.retrieve(order_id, self.key, fields="-items,-metadata")
		self.assertNotIn("items", trimmed)
		self.assertNotIn("metadata", trimmed)
		self.assertEqual(set(trimmed) | {"items", "metadata"}, set(full))
		self.assertEqual(trimmed["total"], full["total"])

		# Unknown fields fail closed — and the internal identity is not a
		# field a client could select either.
		with self.assertRaises(InvalidDataError) as raised:
			self.orders.retrieve(order_id, self.key, fields="sales_order")
		self.assertEqual(raised.exception.status_code, 400)
