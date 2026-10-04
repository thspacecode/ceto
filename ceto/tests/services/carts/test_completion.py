"""Phase 6 completion service tests: the ``CartCompletion`` orchestration.

Runs against real ERPNext controllers on the test site inside a single
rolled-back transaction. Completion locks the cart, runs the preflight
refusal union, submits the Quotation, maps it into a submitted Sales Order
through ERPNext's own mapper (stored pricing preserved), books the
``Ceto Order Reference`` and consumes the cart's credit holds — every
assertion below reads the resulting ERPNext documents, ledger rows and the
pinned response union, not anything derived by Ceto.

The API route is a later chunk; this module drives the service directly.
"""

import uuid
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, flt, getdate, today

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import (
	EMPTY_CART,
	INSUFFICIENT_STOCK,
	MISSING_EMAIL,
	MISSING_SHIPPING_ADDRESS,
	MISSING_SHIPPING_METHOD,
	ORDER_PLACEMENT_FAILED,
	PAYMENT_NOT_READY,
	PAYMENT_READINESS_HOOK,
	STOCK_CHECK_CONFIG,
	CartCompletion,
	new_order_id,
)
from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.services.carts.credits import STORE_CREDITS_EXCEEDED
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import (
	ITEM_PRICE,
	SHIPPING_FLAT_RATE_AMOUNT,
	SHIPPING_FLAT_RATE_LABEL,
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
from ceto.types.http.store.carts.responses import (
	StoreCompleteCartFailure,
	StoreCompleteCartSuccess,
)

LINE_TAX = flt(ITEM_PRICE * TAX_RATE / 100)
PAYABLE = flt(ITEM_PRICE * (1 + TAX_RATE / 100))
CART_TOTAL = flt(PAYABLE + SHIPPING_FLAT_RATE_AMOUNT)

# Hook verdicts recorded by the payment-readiness stubs below.
HOOK_CALLS: list[dict] = []


def decline_payment(**kwargs) -> bool:
	HOOK_CALLS.append(kwargs)
	return False


def approve_payment(**kwargs) -> bool:
	HOOK_CALLS.append(kwargs)
	return True


class TestCartCompletionService(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# An earlier test's committed cart (kept to survive a request
		# rollback) leaves its guest-linked temporary Address behind; ERPNext
		# would refill this module's addressless carts from it as the guest
		# party default and the missing-address refusal would never fire.
		self.masters.discard_committed_cart_temporaries()
		self.completion = CartCompletion()
		self.carts = CartService()
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

	def _cart(
		self,
		*,
		email: str | None = "guest@example.com",
		address: bool = True,
		shipping: bool = True,
		items: int = 1,
	) -> tuple:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, _quotation = self.carts.create(StoreCreateCart(email=email))
			for index in range(items):
				variant = self.masters.item if index == 0 else self.masters.other_item
				self.carts.add_line_item(
					reference.cart_id, StoreAddCartLineItem(variant_id=variant, quantity=1)
				)
			if address:
				self.carts.update(
					reference.cart_id,
					StoreUpdateCart(
						shipping_address=StoreCartAddressPayload(
							address_1="1 Completion Way", city="Bangkok", country_code="th"
						)
					),
				)
			if shipping:
				self.carts.set_shipping_method(
					reference.cart_id,
					StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule),
				)
			return reference, self.carts.retrieve(reference.cart_id)[1]

	def _complete(self, cart_id: str, payload: StoreCompleteCart | None = None, **conf):
		with self.set_conf(ceto_cart=self.masters.configuration, **conf), self.set_user("Guest"):
			return self.completion.complete(cart_id, payload or StoreCompleteCart())

	def _line_id(self, reference) -> str:
		return frappe.get_all(
			"Ceto Cart Line Item Reference", filters={"cart_reference": reference.name}, pluck="line_id"
		)[0]

	def _order_reference(self, cart_id: str):
		return frappe.get_doc(
			"Ceto Order Reference",
			frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name"),
		)

	def _assert_cart_stays_open(self, reference, quotation) -> None:
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))
		loaded = self.carts.retrieve(reference.cart_id)
		self.assertEqual(loaded[1].docstatus, 0)
		self.assertEqual(flt(loaded[1].grand_total), flt(quotation.grand_total))

	def test_completion_places_a_submitted_sales_order(self) -> None:
		reference, quotation = self._cart()

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartSuccess)
		self.assertTrue(response.order.id.startswith("order_"))
		stored = self._order_reference(reference.cart_id)
		self.assertEqual(stored.name, response.order.id)
		self.assertEqual(stored.cart_id, reference.cart_id)
		# A guest order is ownerless: the unguessable id is its capability.
		self.assertIsNone(stored.owner_customer)
		sales_order = frappe.get_doc("Sales Order", stored.sales_order)
		self.assertEqual(sales_order.docstatus, 1)
		self.assertEqual(sales_order.order_type, "Shopping Cart")
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 1)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "status"), "Ordered")
		# The placed order descends from the cart's own Quotation: every
		# mapped row points back at its source row.
		self.assertTrue(sales_order.items)
		for row in sales_order.items:
			self.assertEqual(row.prevdoc_docname, quotation.name)

	def test_completion_snapshots_the_claiming_customer_as_the_order_owner(self) -> None:
		# The owner snapshot rides the settle: it is booked with the order
		# reference inside the same locked transaction (orders Recorded
		# Decision 2), so the placed order already reports the owner.
		email, customer = make_customer_with_user("snapshot")
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			CartClaim().claim(reference.cart_id)
			response = self.completion.complete(reference.cart_id, StoreCompleteCart())

		stored = self._order_reference(reference.cart_id)
		self.assertEqual(stored.owner_customer, customer)
		self.assertEqual(response.order.customer_id, customer)

	def test_order_carries_the_cart_context_and_the_stored_pricing(self) -> None:
		reference, quotation = self._cart()
		cart = CartSerializer().serialize(reference, quotation)

		response = self._complete(reference.cart_id)

		order = response.order
		self.assertEqual(order.email, "guest@example.com")
		self.assertEqual(order.currency_code, quotation.currency.lower())
		self.assertEqual(order.region_id, reference.region_id)
		self.assertEqual(order.sales_channel_id, reference.sales_channel_id)
		self.assertEqual(order.status, "pending")
		self.assertEqual(order.payment_status, "not_paid")
		# Stored pricing preserved: the placed order's rows and totals are
		# the cart's own, produced by ERPNext on both sides.
		sales_order = frappe.get_doc("Sales Order", self._order_reference(reference.cart_id).sales_order)
		self.assertAlmostEqual(flt(sales_order.items[0].rate), ITEM_PRICE)
		self.assertAlmostEqual(flt(sales_order.items[0].price_list_rate), ITEM_PRICE)
		self.assertAlmostEqual(flt(sales_order.grand_total), flt(cart["total"]))
		self.assertAlmostEqual(
			flt(sales_order.total_taxes_and_charges), flt(cart["tax_total"]) + SHIPPING_FLAT_RATE_AMOUNT
		)
		self.assertAlmostEqual(order.total, flt(cart["total"]))
		self.assertAlmostEqual(order.subtotal, flt(cart["subtotal"]))
		self.assertAlmostEqual(order.tax_total, LINE_TAX)
		self.assertAlmostEqual(order.shipping_total, SHIPPING_FLAT_RATE_AMOUNT)
		self.assertAlmostEqual(order.item_subtotal, ITEM_PRICE)
		# The Medusa summary identity holds for the order like it does for
		# the cart: total + discount_total + credit_line_total == subtotal +
		# tax_total.
		self.assertAlmostEqual(
			order.total + order.discount_total + order.credit_line_total,
			order.subtotal + order.tax_total,
		)

	def test_order_lines_keep_the_cart_line_ids(self) -> None:
		reference, _quotation = self._cart()
		line_id = self._line_id(reference)

		response = self._complete(reference.cart_id)

		self.assertEqual(len(response.order.items), 1)
		line = response.order.items[0]
		self.assertEqual(line.id, line_id)
		self.assertEqual(line.order_id, response.order.id)
		self.assertEqual(line.quantity, 1)
		self.assertAlmostEqual(line.unit_price, ITEM_PRICE)
		self.assertAlmostEqual(line.original_unit_price, ITEM_PRICE)
		self.assertAlmostEqual(line.tax_total, LINE_TAX)
		self.assertAlmostEqual(line.total, flt(ITEM_PRICE + LINE_TAX))

	def test_order_reports_the_applied_shipping_method(self) -> None:
		reference, _quotation = self._cart()

		response = self._complete(reference.cart_id)

		methods = response.order.shipping_methods
		self.assertEqual(len(methods), 1)
		self.assertEqual(methods[0].shipping_option_id, self.masters.flat_rate_rule)
		self.assertEqual(methods[0].name, SHIPPING_FLAT_RATE_LABEL)
		self.assertAlmostEqual(methods[0].amount, SHIPPING_FLAT_RATE_AMOUNT)
		self.assertFalse(methods[0].is_tax_inclusive)
		self.assertEqual(methods[0].order_id, response.order.id)

	def test_completed_cart_is_masked_and_the_retry_replays_the_same_order(self) -> None:
		reference, _quotation = self._cart()
		first = self._complete(reference.cart_id)

		# The submitted Quotation takes the cart off every cart route...
		with self.assertRaises(RouteNotFoundError):
			self.carts.retrieve(reference.cart_id)

		# ...and the complete retry replays the placed order instead of
		# mapping a second one.
		second = self._complete(reference.cart_id)
		self.assertIsInstance(second, StoreCompleteCartSuccess)
		self.assertEqual(second.order.id, first.order.id)
		self.assertEqual(frappe.db.count("Ceto Order Reference", {"cart_id": reference.cart_id}), 1)

	def test_unknown_cart_is_not_found(self) -> None:
		with self.assertRaises(RouteNotFoundError):
			self._complete(f"cart_{uuid.uuid4().hex}")

	def test_cancelled_cart_is_not_found(self) -> None:
		reference, quotation = self._cart()
		quotation.submit()
		quotation.cancel()

		with self.assertRaises(RouteNotFoundError):
			self._complete(reference.cart_id)

	def test_empty_cart_is_refused(self) -> None:
		reference, quotation = self._cart(items=0, address=False, shipping=False)

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.type, "cart")
		self.assertEqual(response.cart.id, reference.cart_id)
		self.assertEqual(response.error.name, EMPTY_CART.name)
		self.assertEqual(response.error.type, EMPTY_CART.type)
		self._assert_cart_stays_open(reference, quotation)

	def test_missing_email_is_refused(self) -> None:
		reference, quotation = self._cart(email=None)

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, MISSING_EMAIL.name)
		self.assertEqual(response.error.type, MISSING_EMAIL.type)
		self._assert_cart_stays_open(reference, quotation)

	def test_missing_shipping_address_is_refused(self) -> None:
		reference, quotation = self._cart(address=False)

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, MISSING_SHIPPING_ADDRESS.name)
		self._assert_cart_stays_open(reference, quotation)

	def test_missing_shipping_method_is_refused(self) -> None:
		reference, quotation = self._cart(shipping=False)

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, MISSING_SHIPPING_METHOD.name)
		self._assert_cart_stays_open(reference, quotation)

	def test_payment_gate_is_open_by_default_and_forwards_the_hook_payload(self) -> None:
		reference, _quotation = self._cart()

		# No hook registered: the completion proceeds without a gate.
		response = self._complete(reference.cart_id, StoreCompleteCart(idempotency_key="idem-1"))
		self.assertIsInstance(response, StoreCompleteCartSuccess)

		# A registered hook decides; it receives the cart identity and the
		# submitted idempotency key.
		HOOK_CALLS.clear()
		second_reference, _second_quotation = self._cart()
		with self.patch_hooks({PAYMENT_READINESS_HOOK: [approve_payment_path()]}):
			response = self._complete(second_reference.cart_id, StoreCompleteCart(idempotency_key="idem-2"))

		self.assertIsInstance(response, StoreCompleteCartSuccess)
		self.assertEqual(len(HOOK_CALLS), 1)
		self.assertEqual(HOOK_CALLS[0]["cart_id"], second_reference.cart_id)
		self.assertEqual(HOOK_CALLS[0]["quotation"], _second_quotation.name)
		self.assertEqual(HOOK_CALLS[0]["idempotency_key"], "idem-2")

	def test_payment_gate_fails_closed_on_a_declining_hook(self) -> None:
		reference, quotation = self._cart()

		with self.patch_hooks({PAYMENT_READINESS_HOOK: [decline_payment_path()]}):
			response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, PAYMENT_NOT_READY.name)
		self.assertEqual(response.error.type, PAYMENT_NOT_READY.type)
		self.assertEqual(response.error.message, PAYMENT_NOT_READY.message)
		self._assert_cart_stays_open(reference, quotation)

	def test_a_settle_validation_failure_refuses_the_cart_and_keeps_it_completable(self) -> None:
		# An ERPNext business rule the mapped order violates (raised through
		# frappe.throw, like every ERPNext controller validation) must come
		# back as the pinned OrderPlacementError refusal — not a 500.
		reference, quotation = self._cart()

		with patch(
			"ceto.services.carts.completion.convert_quotation_to_sales_order",
			side_effect=frappe.ValidationError("Credit limit exceeded for customer"),
		):
			response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.type, "cart")
		self.assertEqual(response.error.name, ORDER_PLACEMENT_FAILED.name)
		self.assertEqual(response.error.type, ORDER_PLACEMENT_FAILED.type)
		self.assertEqual(response.error.message, ORDER_PLACEMENT_FAILED.message)
		# The savepoint rollback undid the whole settle: no Sales Order, no
		# order reference, the Quotation is the untouched draft.
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))
		self.assertEqual(frappe.db.count("Sales Order Item", {"prevdoc_docname": quotation.name}), 0)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)
		self._assert_cart_stays_open(reference, quotation)

		# The very same request still completes: the savepoint rollback kept
		# the row locks and the transaction alive.
		retried = self._complete(reference.cart_id)
		self.assertIsInstance(retried, StoreCompleteCartSuccess)

	def test_a_settle_failure_rolls_the_wallet_debits_back(self) -> None:
		code = f"GC-SETTLE-{self.masters.suffix}"
		wallet = self.masters.make_gift_card(code, credit_total=10.0)
		reference, quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.carts.add_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=code))
		hold = frappe.db.get_value("Ceto Cart Credit Reservation", {"quotation": quotation.name}, "name")
		self.assertEqual(frappe.db.get_value("Ceto Cart Credit Reservation", hold, "status"), "Reserved")

		with patch(
			"ceto.services.carts.completion.CartCredits.consume_cart_credits",
			side_effect=frappe.ValidationError("Ledger refused the debit"),
		):
			response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, ORDER_PLACEMENT_FAILED.name)
		self.assertEqual(response.error.type, ORDER_PLACEMENT_FAILED.type)
		# The order, its reference and the wallet debit all rolled back
		# together: the hold is still open, the ledger untouched.
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)
		self.assertEqual(frappe.db.get_value("Ceto Cart Credit Reservation", hold, "status"), "Reserved")
		ledger = frappe.db.get_value("Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True)
		self.assertAlmostEqual(flt(ledger.debit_total), 0)
		self.assertAlmostEqual(flt(ledger.balance), 10.0)

		# The retry settles everything exactly once.
		retried = self._complete(reference.cart_id)
		self.assertIsInstance(retried, StoreCompleteCartSuccess)
		self.assertAlmostEqual(retried.order.gift_card_total, 10.0)
		ledger = frappe.db.get_value("Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True)
		self.assertAlmostEqual(flt(ledger.debit_total), 10.0)
		self.assertAlmostEqual(flt(ledger.balance), 0)
		self.assertEqual(frappe.db.get_value("Ceto Cart Credit Reservation", hold, "status"), "Consumed")

	def test_unexpected_settle_faults_are_not_refused(self) -> None:
		# Only the Frappe/ERPNext validation family maps onto the refusal
		# union; a programming fault must keep failing loudly (the router
		# renders it as 500 and rolls the request back).
		reference, _quotation = self._cart()

		with patch(
			"ceto.services.carts.completion.convert_quotation_to_sales_order",
			side_effect=RuntimeError("boom"),
		):
			with self.assertRaises(RuntimeError):
				self._complete(reference.cart_id)

		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))

	def test_an_unmapped_sales_order_row_refuses_the_completion(self) -> None:
		# A mapper-invented free-item row (no source Quotation Item link)
		# must refuse the completion atomically — never serialize an order
		# with silently invented lines.
		reference, quotation = self._cart()
		real_conversion = convert_quotation_to_sales_order

		def convert_with_free_item(quotation_name: str, *, submit: bool = False):
			sales_order = real_conversion(quotation_name, submit=submit)
			sales_order.append("items", {"item_code": self.masters.other_item, "qty": 1, "rate": 0})
			return sales_order

		with patch(
			"ceto.services.carts.completion.convert_quotation_to_sales_order",
			side_effect=convert_with_free_item,
		):
			response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, ORDER_PLACEMENT_FAILED.name)
		self.assertEqual(response.error.type, ORDER_PLACEMENT_FAILED.type)
		# The pinned refusal carries the stable client-facing identity; the
		# ERPNext reason (the unmapped row) goes to the Error Log.
		logged = frappe.db.get_value(
			"Error Log",
			{"method": "Ceto cart completion settle failed", "error": ("like", f"%{reference.cart_id}%")},
			"error",
			order_by="creation desc",
		)
		self.assertIn(self.masters.other_item, logged)
		# The assert fired before the reference was booked: nothing placed.
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))
		self.assertEqual(frappe.db.count("Sales Order Item", {"prevdoc_docname": quotation.name}), 0)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)

		# Without the rogue row the same cart completes.
		retried = self._complete(reference.cart_id)
		self.assertIsInstance(retried, StoreCompleteCartSuccess)

	def test_the_mapping_assert_rejects_rows_mapped_outside_the_cart_quotation(self) -> None:
		# The cart line mapping is keyed on this Quotation's own item rows;
		# a Sales Order row whose source row belongs to another Quotation is
		# refused exactly like a missing mapping, inside the settle
		# savepoint.
		reference, quotation = self._cart()
		mapping = frappe.get_all(
			"Ceto Cart Line Item Reference",
			filters={"cart_reference": reference.name},
			fields=["name", "quotation_item"],
		)[0]
		# The foreign row comes from this module's own Quotation, built on
		# the bootstrap masters — reading another test's leftover Quotation
		# Item leaves the case empty (and None) on a clean site.
		foreign_quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": self.masters.customer,
				"order_type": "Shopping Cart",
				"company": self.masters.company,
				"currency": frappe.db.get_value("Company", self.masters.company, "default_currency"),
				"conversion_rate": 1,
				"selling_price_list": self.masters.price_list,
				"transaction_date": today(),
				"items": [{"item_code": self.masters.other_item, "qty": 1}],
			}
		).insert(ignore_permissions=True)
		foreign_item = foreign_quotation.items[0]
		frappe.db.set_value(
			"Ceto Cart Line Item Reference", mapping.name, "quotation_item", foreign_item.name
		)
		row = frappe._dict(
			{"name": "row", "item_code": self.masters.item, "quotation_item": foreign_item.name}
		)
		stub_sales_order = type("StubSalesOrder", (), {"name": "SO-TEST", "items": [row]})

		with patch(
			"ceto.services.carts.completion.convert_quotation_to_sales_order",
			return_value=stub_sales_order,
		):
			response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, ORDER_PLACEMENT_FAILED.name)
		self.assertEqual(response.error.type, ORDER_PLACEMENT_FAILED.type)
		# Nothing was placed: no order reference, the submission undone.
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name"))
		self.assertEqual(frappe.db.count("Sales Order Item", {"prevdoc_docname": quotation.name}), 0)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)
		self._assert_cart_stays_open(reference, quotation)

	def test_stock_check_defaults_to_open(self) -> None:
		reference, _quotation = self._cart()
		# The bootstrap ships items without stock ledger entries or bins.
		self.assertIsNone(
			frappe.db.get_value("Bin", {"item_code": self.masters.item, "warehouse": self._warehouse()})
		)

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartSuccess)

	def test_stock_check_refuses_a_shortage_when_enabled(self) -> None:
		reference, quotation = self._cart()
		self._use_warehouse(quotation)

		response = self._complete(reference.cart_id, **{STOCK_CHECK_CONFIG: 1})

		self.assertIsInstance(response, StoreCompleteCartFailure)
		self.assertEqual(response.error.name, INSUFFICIENT_STOCK.name)
		self.assertIn(self.masters.item, response.error.message)
		self._assert_cart_stays_open(reference, quotation)

	def test_stock_check_passes_when_the_warehouse_covers_the_cart(self) -> None:
		reference, quotation = self._cart()
		self._use_warehouse(quotation)
		bin_name = (
			frappe.get_doc({"doctype": "Bin", "item_code": self.masters.item, "warehouse": self._warehouse()})
			.insert(ignore_permissions=True)
			.name
		)
		frappe.db.set_value("Bin", bin_name, "projected_qty", 10, update_modified=False)

		response = self._complete(reference.cart_id, **{STOCK_CHECK_CONFIG: 1})

		self.assertIsInstance(response, StoreCompleteCartSuccess)

	def _warehouse(self) -> str:
		return frappe.db.get_value("Warehouse", {"company": self.masters.company, "is_group": 0}, "name")

	def _use_warehouse(self, quotation) -> None:
		"""Give the cart's item rows a warehouse for the stock check."""
		for row in quotation.items:
			frappe.db.set_value("Quotation Item", row.name, "warehouse", self._warehouse())

	def test_completion_ignores_an_expired_quotation_validity(self) -> None:
		reference, quotation = self._cart()
		# Medusa carts never expire; the ERPNext validity artifact must not
		# block a cart checked out long after creation.
		frappe.db.set_value(
			"Quotation",
			quotation.name,
			"valid_till",
			add_to_date(today(), days=-40),
			update_modified=False,
		)
		quotation = self.carts.retrieve(reference.cart_id)[1]
		self.assertLess(quotation.valid_till, getdate(today()))

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartSuccess)

	def test_completion_consumes_the_gift_card_ledger(self) -> None:
		code = f"GC-DONE-{self.masters.suffix}"
		wallet = self.masters.make_gift_card(code, credit_total=10.0)
		reference, quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.carts.add_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=code))
		quotation = self.carts.retrieve(reference.cart_id)[1]

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartSuccess)
		self.assertAlmostEqual(response.order.gift_card_total, 10.0)
		self.assertAlmostEqual(response.order.credit_line_total, 10.0)
		self.assertAlmostEqual(response.order.total, flt(CART_TOTAL - 10.0))
		# The ledger was debited once, under the same transaction as the
		# placed order; the hold stopped counting as Consumed.
		ledger = frappe.db.get_value("Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True)
		self.assertAlmostEqual(flt(ledger.debit_total), 10.0)
		self.assertAlmostEqual(flt(ledger.balance), 0)
		self.assertEqual(
			frappe.db.get_value(
				"Ceto Cart Credit Reservation",
				{"quotation": quotation.name},
				"status",
			),
			"Consumed",
		)
		sales_order = frappe.get_doc("Sales Order", self._order_reference(reference.cart_id).sales_order)
		self.assertAlmostEqual(flt(sales_order.grand_total), flt(CART_TOTAL - 10.0))

	def test_completion_consumes_the_store_credit_wallet(self) -> None:
		email, customer = make_customer_with_user("done")
		wallet = self.masters.make_store_credit_wallet(customer=customer, credit_total=20.0)
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			self.carts.add_store_credits(reference.cart_id, StoreAddStoreCreditsToCart())

		response = self._complete(reference.cart_id)

		self.assertIsInstance(response, StoreCompleteCartSuccess)
		self.assertAlmostEqual(response.order.credit_line_total, 20.0)
		self.assertAlmostEqual(response.order.gift_card_total, 0)
		self.assertAlmostEqual(response.order.total, flt(CART_TOTAL - 20.0))
		ledger = frappe.db.get_value("Ceto Credit Wallet", wallet, ["debit_total", "balance"], as_dict=True)
		self.assertAlmostEqual(flt(ledger.debit_total), 20.0)
		self.assertAlmostEqual(flt(ledger.balance), 0)
		# The consumed wallet is spent: a fresh cart cannot reserve beyond
		# the ledger remainder.
		second_reference, _second_quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			with self.assertRaisesRegex(InvalidDataError, STORE_CREDITS_EXCEEDED):
				self.carts.add_store_credits(
					second_reference.cart_id, StoreAddStoreCreditsToCart(amount=20.0)
				)

	def test_new_order_id_is_unique_and_prefixed(self) -> None:
		ids = {new_order_id() for _ in range(50)}
		self.assertEqual(len(ids), 50)
		for order_id in ids:
			self.assertTrue(order_id.startswith("order_"))


def approve_payment_path() -> str:
	return "ceto.tests.services.carts.test_completion.approve_payment"


def decline_payment_path() -> str:
	return "ceto.tests.services.carts.test_completion.decline_payment"
