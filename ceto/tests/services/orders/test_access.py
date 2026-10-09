"""Phase 2 order access: resolution, masking and key scope at the service.

Focused access view over the retrieval slice: ``OrderAccess.resolve`` turns
a public ``order_…`` id into its placed-order records and masks every
failure — unknown id, broken lineage, wrong-scoped key — as the same
``404 not_found`` (orders Recorded Decision 5), while retrieval itself
stays capability-based (Recorded Decision 4): the unguessable id is the
only credential, so guests resolve guest orders and any holder of the id
resolves a customer's order. The tests complete real carts through the
service on the test site inside a single rolled-back transaction; broken
lineage is produced the way it can only occur in production — by breaking
recorded state after the fact.
"""

import uuid

import frappe
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing.exceptions import RouteNotFoundError, UnauthorizedError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.access import ORDER_NOT_FOUND, OrderAccess
from ceto.tests.data.cart_test_data import CartTestData, make_customer_with_user
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreAddCartShippingMethods,
	StoreCartAddressPayload,
	StoreCompleteCart,
	StoreCreateCart,
	StoreUpdateCart,
)


class TestOrderAccess(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		self.access = OrderAccess()
		self.key = CartPublishableKey(region_id="reg_test", sales_channel_id="sc_test")
		self.foreign_key = CartPublishableKey(region_id="reg_other", sales_channel_id="sc_other")
		# Frappe throttles user creation per hour; the capability case
		# creates two users per run.
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
						address_1="1 Access Way", city="Bangkok", country_code="th"
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

	def test_resolves_a_placed_order_into_its_records(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_reference = self._order_reference(reference.cart_id)

		resolved = self.access.resolve(order_reference.order_id, self.key)

		self.assertEqual(resolved[0].name, order_reference.name)
		self.assertEqual(resolved[0].order_id, order_reference.order_id)
		# The submitted ERPNext Sales Order the reference books.
		self.assertEqual(resolved[1].name, order_reference.sales_order)
		self.assertEqual(resolved[1].docstatus, 1)
		# The completed cart's reference — the cart context.
		self.assertEqual(resolved[2].name, reference.cart_id)

	def test_masks_an_unknown_order_as_not_found(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)

		with self.assertRaises(RouteNotFoundError) as raised:
			self.access.resolve(f"order_{uuid.uuid4().hex}", self.key)

		self.assertEqual(raised.exception.message, ORDER_NOT_FOUND)
		self.assertEqual(raised.exception.error_type, "not_found")
		self.assertEqual(raised.exception.status_code, 404)

	def test_a_wrong_scoped_key_is_masked_as_not_found(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_id = self._order_reference(reference.cart_id).order_id
		wrong_keys = (
			CartPublishableKey(region_id="reg_other"),
			CartPublishableKey(sales_channel_id="sc_other"),
			self.foreign_key,
		)

		for key in wrong_keys:
			with self.subTest(key=key), self.assertRaises(RouteNotFoundError) as raised:
				self.access.resolve(order_id, key)
			self.assertEqual(raised.exception.message, ORDER_NOT_FOUND)

	def test_an_unconstrained_or_matching_key_resolves_the_order(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_id = self._order_reference(reference.cart_id).order_id

		for key in (
			CartPublishableKey(),
			CartPublishableKey(region_id="reg_test"),
			CartPublishableKey(sales_channel_id="sc_test"),
			self.key,
		):
			with self.subTest(key=key):
				self.assertEqual(self.access.resolve(order_id, key)[0].order_id, order_id)

	def test_retrieval_is_capability_based_not_ownership_gated(self) -> None:
		# Recorded Decision 4: the unguessable id is the credential for
		# whoever holds it — adding a customer gate would be an
		# upstream-incompatible invention.
		email, _customer = make_customer_with_user("capability")
		holder, _holder_customer = make_customer_with_user("holder")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		self._complete(reference, user=email)
		order_id = self._order_reference(reference.cart_id).order_id

		with self.set_user("Guest"):
			self.assertEqual(self.access.resolve(order_id, self.key)[0].order_id, order_id)
		with self.set_user(holder):
			self.assertEqual(self.access.resolve(order_id, self.key)[0].order_id, order_id)

	def test_broken_lineage_is_masked_as_not_found(self) -> None:
		cases = {
			"dangling cart reference": lambda order_reference, _cart_reference: frappe.db.set_value(
				"Ceto Order Reference",
				order_reference.name,
				"cart_id",
				f"cart_{uuid.uuid4().hex}",
				update_modified=False,
			),
			"dangling sales order": lambda order_reference, _cart_reference: frappe.db.set_value(
				"Ceto Order Reference",
				order_reference.name,
				"sales_order",
				f"SORD-{uuid.uuid4().hex}",
				update_modified=False,
			),
			"cancelled lineage": lambda _order_reference, cart_reference: frappe.db.set_value(
				"Quotation", cart_reference.quotation, "docstatus", 2, update_modified=False
			),
			"drafted lineage": lambda _order_reference, cart_reference: frappe.db.set_value(
				"Quotation", cart_reference.quotation, "docstatus", 0, update_modified=False
			),
		}
		for label, breakage in cases.items():
			with self.subTest(case=label):
				reference, _quotation = self._cart()
				self._complete(reference)
				order_reference = self._order_reference(reference.cart_id)
				cart_reference = frappe.get_doc("Ceto Cart Reference", reference.cart_id)

				breakage(order_reference, cart_reference)

				with self.assertRaises(RouteNotFoundError) as raised:
					self.access.resolve(order_reference.order_id, self.key)
				self.assertEqual(raised.exception.message, ORDER_NOT_FOUND)

	def test_every_masked_failure_is_the_same_safe_error(self) -> None:
		reference, _quotation = self._cart()
		self._complete(reference)
		order_reference = self._order_reference(reference.cart_id)
		frappe.db.set_value(
			"Ceto Order Reference", order_reference.name, "sales_order", f"SORD-{uuid.uuid4().hex}"
		)

		with self.assertRaises(RouteNotFoundError) as unknown:
			self.access.resolve(f"order_{uuid.uuid4().hex}", self.key)
		with self.assertRaises(RouteNotFoundError) as foreign:
			self.access.resolve(order_reference.order_id, self.foreign_key)
		with self.assertRaises(RouteNotFoundError) as broken:
			self.access.resolve(order_reference.order_id, self.key)

		for raised in (unknown, foreign, broken):
			self.assertEqual(type(raised.exception), RouteNotFoundError)
			self.assertEqual(raised.exception.message, unknown.exception.message)
			self.assertEqual(raised.exception.status_code, unknown.exception.status_code)

	def test_the_key_is_resolved_the_store_authentication_way(self) -> None:
		# The authentication step the retrieve route performs — the same
		# ``from_request`` every store route uses — rejects a missing or
		# unknown key as 401 before any order is looked up, and resolves
		# the configured key to the scope the resolution enforces.
		configuration = {
			**self.masters.configuration,
			"publishable_keys": {"pk_test": {"region_id": "reg_test", "sales_channel_id": "sc_test"}},
		}
		with self.set_conf(ceto_cart=configuration):
			for headers in (None, {"x-publishable-api-key": "pk_unknown"}):
				with self.subTest(headers=headers):
					builder = EnvironBuilder(
						path="/", method="GET", headers=headers, environ_base={"REMOTE_ADDR": "127.0.0.1"}
					)
					with self.set_request(Request(builder.get_environ())):
						with self.assertRaises(UnauthorizedError) as raised:
							CartPublishableKey.from_request()
					self.assertEqual(raised.exception.status_code, 401)

			builder = EnvironBuilder(
				path="/",
				method="GET",
				headers={"x-publishable-api-key": "pk_test"},
				environ_base={"REMOTE_ADDR": "127.0.0.1"},
			)
			with self.set_request(Request(builder.get_environ())):
				self.assertEqual(CartPublishableKey.from_request(), self.key)
