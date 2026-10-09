"""Phase 1 order ownership: the snapshot, the legacy fallback, the backfill.

The completing transaction snapshots the cart's ``owner_customer`` onto the
``Ceto Order Reference`` inside the settle (orders Recorded Decision 2), the
order serializer reads the reference's effective owner through
``OrderOwnership`` — snapshot first, completed cart as the Phase 6 legacy
fallback (Recorded Decision 3) — and the backfill patch copies that fallback
onto legacy references once, without moving ``modified``. The tests complete
real carts through the service on the test site inside a single rolled-back
transaction; the Sales Order's customer links are pinned as never being
ownership evidence.
"""

import json
import uuid

import frappe

from ceto.patches.orders.order_owner_customer_backfill import execute as backfill_owner_snapshots
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.completion import CartCompletion
from ceto.services.carts.quotation import CartService
from ceto.services.orders.ownership import OrderOwnership
from ceto.services.orders.serialization import OrderSerializer
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


class TestOrderOwnership(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		self.carts = CartService()
		self.completion = CartCompletion()
		# Frappe throttles user creation per hour; every claimed fixture
		# creates one user.
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
						address_1="1 Ownership Way", city="Bangkok", country_code="th"
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

	def _complete(self, reference):
		with self.set_conf(ceto_cart=self.masters.configuration):
			return self.completion.complete(reference.cart_id, StoreCompleteCart())

	def _order_reference(self, cart_id: str):
		return frappe.get_doc(
			"Ceto Order Reference", frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}, "name")
		)

	def _strip_snapshot(self, order_reference) -> None:
		"""Turn the reference into its Phase 6 legacy shape (no snapshot)."""
		frappe.db.set_value(
			"Ceto Order Reference", order_reference.name, "owner_customer", None, update_modified=False
		)

	def test_completion_snapshots_the_claiming_customer_as_the_order_owner(self) -> None:
		email, customer = make_customer_with_user("snapshot")
		reference, _quotation = self._cart()
		self._claim(reference, email)

		with self.set_user(email):
			response = self._complete(reference)

		stored = self._order_reference(reference.cart_id)
		self.assertEqual(stored.owner_customer, customer)
		# The serialized order reports the snapshot as the Medusa customer_id.
		self.assertEqual(response.order.customer_id, customer)

	def test_guest_orders_are_born_ownerless(self) -> None:
		reference, _quotation = self._cart()

		with self.set_user("Guest"):
			response = self._complete(reference)

		stored = self._order_reference(reference.cart_id)
		self.assertIsNone(stored.owner_customer)
		self.assertIsNone(response.order.customer_id)

	def test_the_snapshot_is_the_live_source_not_the_cart_history(self) -> None:
		email, customer = make_customer_with_user("live")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		with self.set_user(email):
			self._complete(reference)
		stored = self._order_reference(reference.cart_id)

		# Neither the completed cart's ownership nor the Sales Order's
		# customer links are ownership evidence: the snapshot wins alone.
		frappe.db.set_value("Ceto Cart Reference", reference.cart_id, "owner_customer", None)
		frappe.db.set_value("Sales Order", stored.sales_order, "customer", self.masters.customer)

		reloaded = frappe.get_doc("Ceto Order Reference", stored.name)
		self.assertEqual(OrderOwnership.effective_owner(reloaded), customer)

	def test_legacy_references_fall_back_to_the_completed_cart_owner(self) -> None:
		email, customer = make_customer_with_user("legacy")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		with self.set_user(email):
			self._complete(reference)
		stored = self._order_reference(reference.cart_id)
		self._strip_snapshot(stored)

		reloaded = frappe.get_doc("Ceto Order Reference", stored.name)
		self.assertIsNone(reloaded.owner_customer)
		self.assertEqual(OrderOwnership.effective_owner(reloaded), customer)

	def test_legacy_guest_orders_and_dangling_carts_resolve_to_no_owner(self) -> None:
		reference, _quotation = self._cart()
		with self.set_user("Guest"):
			self._complete(reference)
		stored = self._order_reference(reference.cart_id)
		# A guest legacy row: no snapshot, and the cart has no owner either.
		self._strip_snapshot(stored)

		reloaded = frappe.get_doc("Ceto Order Reference", stored.name)
		self.assertIsNone(OrderOwnership.effective_owner(reloaded))

		# A dangling cart reference degrades to None instead of raising.
		frappe.db.set_value(
			"Ceto Order Reference", stored.name, "cart_id", f"cart_{uuid.uuid4().hex}", update_modified=False
		)
		reloaded = frappe.get_doc("Ceto Order Reference", stored.name)
		self.assertIsNone(OrderOwnership.effective_owner(reloaded))

	def test_replay_output_is_byte_compatible_across_the_legacy_fallback(self) -> None:
		email, customer = make_customer_with_user("replay")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		with self.set_user(email):
			first = self._complete(reference)
		stored = self._order_reference(reference.cart_id)
		self._strip_snapshot(stored)

		# The replay reads the legacy reference through the fallback and
		# ships the exact same order JSON — customer_id included.
		with self.set_user(email):
			second = self._complete(reference)

		self.assertEqual(second.order.id, first.order.id)
		self.assertEqual(
			json.dumps(second.order.model_dump(mode="json")), json.dumps(first.order.model_dump(mode="json"))
		)

		# The order serializer resolves the effective owner the same way.
		order_reference = frappe.get_doc("Ceto Order Reference", stored.name)
		sales_order = frappe.get_doc("Sales Order", stored.sales_order)
		cart_reference = frappe.get_doc("Ceto Cart Reference", reference.cart_id)
		order = OrderSerializer().serialize(order_reference, sales_order, cart_reference)
		self.assertEqual(order["customer_id"], customer)

	def test_the_backfill_patch_copies_the_cart_owner_without_touching_modified(self) -> None:
		email, customer = make_customer_with_user("backfill")
		reference, _quotation = self._cart()
		self._claim(reference, email)
		with self.set_user(email):
			self._complete(reference)
		stored = self._order_reference(reference.cart_id)
		self._strip_snapshot(stored)
		modified_before = frappe.db.get_value("Ceto Order Reference", stored.name, "modified")

		# The one-time backfill is idempotent and never moves ``modified`` —
		# the serialized order's ``updated_at`` stays byte-stable across the
		# migration.
		backfill_owner_snapshots()
		backfill_owner_snapshots()

		self.assertEqual(frappe.db.get_value("Ceto Order Reference", stored.name, "owner_customer"), customer)
		self.assertEqual(
			frappe.db.get_value("Ceto Order Reference", stored.name, "modified"), modified_before
		)

		# A legacy guest order stays ownerless.
		guest_reference, _guest_quotation = self._cart()
		with self.set_user("Guest"):
			self._complete(guest_reference)
		backfill_owner_snapshots()
		guest_stored = self._order_reference(guest_reference.cart_id)
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", guest_stored.name, "owner_customer"))
