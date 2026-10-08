"""Phase 6 order serialization: the placed order read back from its records.

Focused serializer view over the records the completion service books (the
completion flow itself is covered by
``ceto.tests.services.carts.test_completion``). The tests complete a real
cart through the service on the test site inside a single rolled-back
transaction, then assert on the ``OrderSerializer`` output: the pinned
``StoreOrder`` JSON derived from the ERPNext Sales Order, the cart
reference and the consumed credit holds — with the same carve-out
arithmetic and summary identity the cart serializer pins. The customer
cases pin the nullable embedded ``StoreCustomer``: a reference-backed
claimed owner, a reference-less claimed owner (ERPNext ``customer_id``
only), a guest null and the replay equality.
"""

import frappe
from frappe.utils import flt

from ceto.ceto.doctype.ceto_customer_reference.ceto_customer_reference import mint_customer_id
from ceto.routing.exceptions import InternalServerError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.serialization import OrderSerializer
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
	StoreAddGiftCardToCart,
	StoreAddStoreCreditsToCart,
	StoreCartAddressPayload,
	StoreCompleteCart,
	StoreCreateCart,
	StoreUpdateCart,
)

LINE_TAX = flt(ITEM_PRICE * TAX_RATE / 100)
CART_TOTAL = flt(ITEM_PRICE * (1 + TAX_RATE / 100) + SHIPPING_FLAT_RATE_AMOUNT)


class TestOrderSerialization(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.claims = CartClaim()
		self.completion = CartCompletion()
		self.serializer = OrderSerializer()
		# Frappe throttles user creation per hour; the store-credit case
		# creates one user per run.
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
						address_1="1 Serialization Way", city="Bangkok", country_code="th"
					)
				),
			)
			self.carts.set_shipping_method(
				reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)
			return self.carts.retrieve(reference.cart_id)

	def _completed_cart(self, reference, *, user: str = "Guest") -> tuple:
		"""Complete the cart through the service; return its records."""
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(user):
			response = self.completion.complete(reference.cart_id, StoreCompleteCart())
		order_reference = frappe.get_doc("Ceto Order Reference", response.order.id)
		sales_order = frappe.get_doc("Sales Order", order_reference.sales_order)
		return order_reference, sales_order

	def _customer_reference(self, email: str, customer: str):
		"""Book the public ``cus_…`` identity for a cart owner's chain."""
		return frappe.get_doc(
			{
				"doctype": "Ceto Customer Reference",
				"customer_id": mint_customer_id(),
				"customer": customer,
				"user": email,
			}
		).insert(ignore_permissions=True)

	def _claimed_cart(self, email: str) -> tuple:
		"""Claim the checkout-ready guest cart for ``email``'s Customer."""
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			claimed, _quotation = self.claims.claim(reference.cart_id)
		return claimed

	def test_serializes_the_placed_order_from_its_records(self) -> None:
		reference, _quotation = self._cart()
		# Give the cart a locale: it stays a cart-only column and must not
		# leak onto the order.
		self.carts.update(reference.cart_id, StoreUpdateCart(locale="th-TH"))
		order_reference, sales_order = self._completed_cart(reference)

		order = self.serializer.serialize(order_reference, sales_order, reference)

		self.assertEqual(order["id"], order_reference.order_id)
		self.assertEqual(order["currency_code"], sales_order.currency.lower())
		self.assertEqual(order["email"], "guest@example.com")
		self.assertEqual(order["region_id"], reference.region_id)
		self.assertEqual(order["sales_channel_id"], reference.sales_channel_id)
		self.assertEqual(order["status"], "pending")
		self.assertEqual(order["payment_status"], "not_paid")
		self.assertEqual(order["fulfillment_status"], "not_fulfilled")
		# A guest order has no owner: the unguessable id is its capability.
		self.assertIsNone(order["customer_id"])
		# The cart's locale is a cart-only column: the pinned StoreOrder has
		# no locale, so the order never reports one.
		self.assertNotIn("locale", order)
		# Shipping address serialized from the ERPNext Address the cart
		# created; the display ids stay omitted (Recorded Decision 9).
		self.assertEqual(order["shipping_address"]["city"], "Bangkok")
		self.assertEqual(order["shipping_address"]["country_code"], "th")
		self.assertNotIn("display_id", order)
		self.assertNotIn("custom_display_id", order)
		# The pinned summary identity with no credits on the cart.
		self.assertAlmostEqual(
			order["total"] + order["discount_total"] + order["credit_line_total"],
			order["subtotal"] + order["tax_total"],
		)
		self.assertAlmostEqual(order["total"], CART_TOTAL)
		self.assertAlmostEqual(order["tax_total"], LINE_TAX)
		self.assertAlmostEqual(order["shipping_total"], SHIPPING_FLAT_RATE_AMOUNT)

	def test_order_lines_and_shipping_mirror_the_sales_order(self) -> None:
		reference, _quotation = self._cart()
		order_reference, sales_order = self._completed_cart(reference)
		line_id = frappe.get_all(
			"Ceto Cart Line Item Reference", filters={"cart_reference": reference.name}, pluck="line_id"
		)[0]

		order = self.serializer.serialize(order_reference, sales_order, reference)

		self.assertEqual(len(order["items"]), len(sales_order.items))
		line = order["items"][0]
		self.assertEqual(line["id"], line_id)
		self.assertEqual(line["order_id"], order["id"])
		self.assertEqual(line["variant_id"], self.masters.item)
		self.assertEqual(line["quantity"], 1)
		self.assertAlmostEqual(line["unit_price"], ITEM_PRICE)
		self.assertAlmostEqual(line["tax_total"], LINE_TAX)
		self.assertEqual(len(order["shipping_methods"]), 1)
		self.assertEqual(order["shipping_methods"][0]["shipping_option_id"], self.masters.flat_rate_rule)
		self.assertAlmostEqual(order["shipping_methods"][0]["amount"], SHIPPING_FLAT_RATE_AMOUNT)

	def test_an_unmapped_sales_order_row_fails_loudly_instead_of_being_skipped(self) -> None:
		# Defense-in-depth for the completion's own pre-insert assert: a row
		# without a cart line mapping (e.g. an ERPNext free item the mapper
		# invented) must never silently vanish from the serialized order.
		reference, _quotation = self._cart()
		order_reference, sales_order = self._completed_cart(reference)
		sales_order.append(
			"items",
			{"item_code": self.masters.other_item, "quotation_item": None, "qty": 1, "rate": 0},
		)

		with self.assertRaises(InternalServerError) as raised:
			self.serializer.serialize(order_reference, sales_order, reference)

		self.assertIn(self.masters.other_item, str(raised.exception))

	def test_consumed_credits_are_the_order_credit_totals(self) -> None:
		code = f"GC-ORDER-{self.masters.suffix}"
		self.masters.make_gift_card(code, credit_total=10.0)
		email, customer = make_customer_with_user("order")
		self.masters.make_store_credit_wallet(customer=customer, credit_total=15.0)
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.carts.add_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=code))
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			self.carts.add_store_credits(reference.cart_id, StoreAddStoreCreditsToCart(amount=5.0))
		order_reference, sales_order = self._completed_cart(reference)

		order = self.serializer.serialize(order_reference, sales_order, reference)

		# The gift card (10) plus the store credit (5): one credit line
		# total, the gift-card share split out — carved out of the tax
		# fields exactly like on the cart, so the identity still holds.
		self.assertAlmostEqual(order["gift_card_total"], 10.0)
		self.assertAlmostEqual(order["credit_line_total"], 15.0)
		self.assertAlmostEqual(order["total"], flt(CART_TOTAL - 15.0))
		self.assertAlmostEqual(
			order["total"] + order["discount_total"] + order["credit_line_total"],
			order["subtotal"] + order["tax_total"],
		)
		self.assertEqual(
			frappe.db.count(
				"Ceto Cart Credit Reservation",
				{"quotation": reference.quotation, "status": "Consumed"},
			),
			2,
		)

	def test_a_guest_order_reports_no_customer(self) -> None:
		reference, _quotation = self._cart()
		order_reference, sales_order = self._completed_cart(reference)

		order = self.serializer.serialize(order_reference, sales_order, reference)

		# A guest owns no contract-safe customer identity: the embedded
		# column stays null instead of inventing one (the pinned StoreOrder
		# carries the customer as a nullable relation), and customer_id
		# keeps its historical guest null.
		self.assertIsNone(order["customer"])
		self.assertIsNone(order["customer_id"])

	def test_a_claimed_order_embeds_the_reference_backed_customer(self) -> None:
		email, customer = make_customer_with_user("order-customer")
		customer_reference = self._customer_reference(email, customer)
		cart_reference = self._claimed_cart(email)
		order_reference, sales_order = self._completed_cart(cart_reference, user=email)

		order = self.serializer.serialize(order_reference, sales_order, cart_reference)

		# The embedded customer is the customers contract's pinned identity:
		# the stable cus_… id, the identity email and the address book the
		# claim copied onto the Customer — the exact StoreCustomer the
		# customers serializer builds, never a re-derived one.
		self.assertEqual(order["customer"]["id"], customer_reference.name)
		self.assertEqual(order["customer"]["email"], email)
		self.assertEqual(len(order["customer"]["addresses"]), 1)
		self.assertEqual(order["customer"]["addresses"][0]["city"], "Bangkok")
		# The recorded compatibility deviation: customer_id keeps the
		# historical ERPNext Customer-name mapping beside the embedded
		# cus_… id (the two deliberately disagree).
		self.assertEqual(order["customer_id"], customer)
		self.assertNotEqual(order["customer_id"], order["customer"]["id"])

	def test_a_reference_less_claimed_order_keeps_only_the_erpnext_customer_id(self) -> None:
		# A pre-existing ERPNext account linked outside Ceto can claim and
		# complete a cart (the claim resolves the identity chain alone), but
		# it owns no public cus_… identity: the order embeds no customer
		# instead of inventing one, while customer_id keeps the ERPNext
		# Customer name the carts surface has always reported.
		email, customer = make_customer_with_user("order-no-reference")
		cart_reference = self._claimed_cart(email)
		order_reference, sales_order = self._completed_cart(cart_reference, user=email)

		order = self.serializer.serialize(order_reference, sales_order, cart_reference)

		self.assertIsNone(order["customer"])
		self.assertEqual(order["customer_id"], customer)

	def test_the_replayed_completion_serializes_the_same_customer(self) -> None:
		email, customer = make_customer_with_user("order-replay")
		self._customer_reference(email, customer)
		cart_reference = self._claimed_cart(email)
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			first = self.completion.complete(cart_reference.cart_id, StoreCompleteCart())
			replayed = self.completion.complete(cart_reference.cart_id, StoreCompleteCart())

		# The replay re-serializes the same placed order from the same
		# records: the embedded customer is equal, not re-derived.
		self.assertEqual(first.order.id, replayed.order.id)
		self.assertEqual(first.order.customer, replayed.order.customer)
		self.assertEqual(replayed.order.customer.id, first.order.customer.id)
