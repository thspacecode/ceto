"""Phase 3 order listing: the pinned ``{orders, count, offset, limit}`` page.

Focused listing view over the slice: ``OrderService.list`` pages a
customer's placed orders out of the scoped read model — strictly scoped to
the authenticated customer (orders Recorded Decision 2) and the publishable
key (Decision 5), guest orders belonging to no list (Decision 4), ordered
``creation DESC, order_id ASC`` (Decision 7), counted exactly before
pagination and filtered by the pinned ``id``/``status`` domain (Decision 8)
— and the page is served through the same ``OrderSerializer`` as retrieve,
so one order in a page is byte-identical to its retrieval while the query
count stays bounded as the page grows. The tests complete real carts
through the service on the test site inside a single rolled-back
transaction.
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

import frappe

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import UnauthorizedError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.listing import ORDER_LIST_MAX_LIMIT
from ceto.services.orders.service import OrderService
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
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
from ceto.types.http.store.orders.manifest import (
	ORDER_LIST_DEFAULT_LIMIT,
	ORDER_LIST_DEFAULT_OFFSET,
)


class TestOrderListing(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.service = OrderService()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		# Frappe throttles user creation per hour; every case creates its
		# own customer.
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
						address_1="1 Listing Way", city="Bangkok", country_code="th"
					)
				),
			)
			self.carts.set_shipping_method(
				reference.cart_id, StoreAddCartShippingMethods(option_id=self.masters.flat_rate_rule)
			)
			return self.carts.retrieve(reference.cart_id)

	def _claim(self, reference, email: str) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			CartClaim().claim(reference.cart_id)

	def _complete(self, reference, *, user: str = "Guest"):
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(user):
			return self.completion.complete(reference.cart_id, StoreCompleteCart())

	def _order_reference(self, cart_id: str):
		return frappe.get_doc(
			"Ceto Order Reference", frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name")
		)

	def _placed_order(self, email: str):
		"""Claim and complete one cart for ``email``; return its order reference."""
		reference, _quotation = self._cart()
		self._claim(reference, email)
		self._complete(reference, user=email)
		return self._order_reference(reference.cart_id)

	def _guest_order(self):
		"""Complete one unclaimed cart; the placed order belongs to nobody."""
		reference, _quotation = self._cart()
		self._complete(reference)
		return self._order_reference(reference.cart_id)

	@contextmanager
	def _sql_queries(self) -> Iterator[mock.Mock]:
		"""Spy on ``frappe.db.sql`` for the block: the query builder and
		``frappe.get_all`` both run through it."""
		with mock.patch.object(frappe.db, "sql", wraps=frappe.db.sql) as spy:
			yield spy

	def test_lists_the_customer_placed_orders_newest_first(self) -> None:
		email, customer = make_customer_with_user("listing")
		placed = [self._placed_order(email) for _ in range(3)]
		guest_order = self._guest_order()

		page = self.service.list(customer, self.key)

		self.assertEqual(set(page), {"orders", "count", "offset", "limit"})
		self.assertEqual(page["count"], 3)
		self.assertEqual(page["offset"], ORDER_LIST_DEFAULT_OFFSET)
		self.assertEqual(page["limit"], ORDER_LIST_DEFAULT_LIMIT)
		# Newest first with the id tiebreak (Recorded Decision 7).
		self.assertEqual(
			[order["id"] for order in page["orders"]],
			[reference.order_id for reference in reversed(placed)],
		)
		# Every served order belongs to the asking customer.
		self.assertEqual({order["customer_id"] for order in page["orders"]}, {customer})
		# A guest order belongs to no list (Recorded Decision 4): not even
		# the guest party its Sales Order names can list it.
		self.assertNotIn(guest_order.order_id, [order["id"] for order in page["orders"]])
		self.assertEqual(self.service.list(self.masters.customer, self.key)["count"], 0)

	def test_an_anonymous_list_is_refused(self) -> None:
		with self.assertRaises(UnauthorizedError):
			self.service.list("", self.key)

	def test_pagination_slices_and_counts_the_scoped_ledger(self) -> None:
		email, customer = make_customer_with_user("pagination")
		placed = [self._placed_order(email) for _ in range(2)]
		newest, oldest = placed[1].order_id, placed[0].order_id

		first = self.service.list(customer, self.key, limit=1, offset=0)
		self.assertEqual(first["count"], 2)
		self.assertEqual([order["id"] for order in first["orders"]], [newest])
		self.assertEqual((first["limit"], first["offset"]), (1, 0))

		second = self.service.list(customer, self.key, limit=1, offset=1)
		self.assertEqual(second["count"], 2)
		self.assertEqual([order["id"] for order in second["orders"]], [oldest])

		beyond = self.service.list(customer, self.key, limit=1, offset=2)
		self.assertEqual(beyond["orders"], [])
		self.assertEqual(beyond["count"], 2)

		# The envelope echoes the effective offset/limit: the read model
		# bounds ``limit`` so a page's bulk load stays bounded, and the
		# page numbers are non-negative.
		self.assertEqual(self.service.list(customer, self.key, limit=1000)["limit"], ORDER_LIST_MAX_LIMIT)
		clamped = self.service.list(customer, self.key, limit=-1, offset=-5)
		self.assertEqual((clamped["limit"], clamped["offset"]), (0, 0))
		self.assertEqual(clamped["orders"], [])
		self.assertEqual(clamped["count"], 2)

	def test_orders_of_another_customer_stay_out_of_the_page(self) -> None:
		email, customer = make_customer_with_user("owner")
		stranger_email, stranger = make_customer_with_user("stranger")
		placed = [self._placed_order(email) for _ in range(2)]
		self._placed_order(stranger_email)

		mine = self.service.list(customer, self.key)
		self.assertEqual(mine["count"], 2)
		self.assertEqual(
			{order["id"] for order in mine["orders"]}, {reference.order_id for reference in placed}
		)

		theirs = self.service.list(stranger, self.key)
		self.assertEqual(theirs["count"], 1)
		self.assertEqual(theirs["orders"][0]["customer_id"], stranger)
		self.assertNotIn(placed[0].order_id, [order["id"] for order in theirs["orders"]])

	def test_the_publishable_key_scopes_the_page(self) -> None:
		email, customer = make_customer_with_user("scoped")
		order = self._placed_order(email)
		other_region = CartPublishableKey(region_id="reg_other")
		other_channel = CartPublishableKey(sales_channel_id="sc_other")
		open_key = CartPublishableKey()

		# The order inherits its completed cart's scope; a key scoped
		# elsewhere lists nothing — the comparison the retrieve path masks
		# as 404 filters here (Recorded Decision 5).
		frappe.db.set_value(
			"Ceto Cart Reference", order.cart_id, "region_id", "reg_other", update_modified=False
		)
		self.assertEqual(self.service.list(customer, self.key)["count"], 0)
		self.assertEqual(self.service.list(customer, other_region)["count"], 1)
		# An unconstraining key constrains nothing.
		self.assertEqual(self.service.list(customer, open_key)["count"], 1)

		frappe.db.set_value(
			"Ceto Cart Reference", order.cart_id, "region_id", "reg_test", update_modified=False
		)
		frappe.db.set_value(
			"Ceto Cart Reference", order.cart_id, "sales_channel_id", "sc_other", update_modified=False
		)
		self.assertEqual(self.service.list(customer, self.key)["count"], 0)
		self.assertEqual(self.service.list(customer, other_channel)["count"], 1)

	def test_the_id_filter_narrows_the_page(self) -> None:
		email, customer = make_customer_with_user("filter")
		placed = [self._placed_order(email) for _ in range(2)]

		page = self.service.list(customer, self.key, ids=placed[0].order_id)
		self.assertEqual(page["count"], 1)
		self.assertEqual([order["id"] for order in page["orders"]], [placed[0].order_id])

		both = self.service.list(customer, self.key, ids=[reference.order_id for reference in placed])
		self.assertEqual(both["count"], 2)

		missing = self.service.list(customer, self.key, ids=[f"order_{uuid.uuid4().hex}"])
		self.assertEqual(missing["orders"], [])
		self.assertEqual(missing["count"], 0)

	def test_the_status_filter_matches_only_the_reported_status(self) -> None:
		email, customer = make_customer_with_user("status")
		self._placed_order(email)

		# Every placed order reports ``pending`` (Recorded Decision 6):
		# the reported member matches, every other union member matches
		# nothing — exactly as upstream, which accepts any string and
		# answers with an empty page too.
		self.assertEqual(self.service.list(customer, self.key, statuses="pending")["count"], 1)
		self.assertEqual(self.service.list(customer, self.key, statuses=["completed"])["count"], 0)
		mixed = self.service.list(customer, self.key, statuses=["canceled", "pending"])
		self.assertEqual(mixed["count"], 1)
		self.assertEqual(self.service.list(customer, self.key, statuses=["archived", "draft"])["count"], 0)

	def test_a_page_order_is_byte_identical_to_its_retrieval(self) -> None:
		email, customer = make_customer_with_user("equivalence")
		code = f"GC-LIST-{self.masters.suffix}"
		self.masters.make_gift_card(code, credit_total=10.0)
		self.masters.make_store_credit_wallet(customer=customer, credit_total=15.0)
		reference, _quotation = self._cart()
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			self.carts.add_gift_card(reference.cart_id, StoreAddGiftCardToCart(code=code))
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user(email):
			self.carts.add_store_credits(reference.cart_id, StoreAddStoreCreditsToCart(amount=5.0))
		self._claim(reference, email)
		self._complete(reference, user=email)
		order_reference = self._order_reference(reference.cart_id)

		served = self.service.retrieve(order_reference.order_id, self.key)
		page = self.service.list(customer, self.key, ids=order_reference.order_id)

		self.assertEqual(page["count"], 1)
		# The page context bulk-loads what retrieve reads per order — the
		# served representation is identical either way, credits included.
		self.assertEqual(
			json.dumps(page["orders"][0], sort_keys=True),
			json.dumps(served, sort_keys=True),
		)
		self.assertEqual(page["orders"][0]["gift_card_total"], 10.0)
		self.assertEqual(page["orders"][0]["credit_line_total"], 15.0)

		# The shared ``fields`` selector applies to every served order.
		narrowed = self.service.list(customer, self.key, fields="id,status,total")
		for order in narrowed["orders"]:
			self.assertEqual(set(order), {"id", "status", "total"})
		self.assertEqual(narrowed["orders"][0]["total"], served["total"])

	def test_the_whole_page_costs_the_same_queries_as_one_order(self) -> None:
		email, customer = make_customer_with_user("bounded")
		placed = [self._placed_order(email) for _ in range(3)]
		self.service.list(customer, self.key)  # warm the per-request caches

		with self._sql_queries() as single:
			page = self.service.list(customer, self.key, ids=placed[0].order_id)
		with self._sql_queries() as whole:
			full = self.service.list(customer, self.key)

		self.assertEqual(len(page["orders"]), 1)
		self.assertEqual(len(full["orders"]), 3)
		# Every page-wide read is one IN query: three orders cost no more
		# than one — the query count is bounded, never per-order.
		self.assertGreater(single.call_count, 0)
		self.assertLessEqual(whole.call_count, single.call_count)
