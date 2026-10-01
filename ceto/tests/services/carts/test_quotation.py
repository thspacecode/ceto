from unittest.mock import patch

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCreateCart,
	StoreUpdateCart,
)


class TestCartQuotation(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# The claim-visibility test creates Website Users; Frappe throttles
		# user creation per hour on the shared test site, so lift it here like
		# the other user-creating cart modules do.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def test_creates_and_retrieves_guest_cart(self) -> None:
		payload = StoreCreateCart(
			email="guest@example.com",
			metadata={"source": "test"},
			locale="en-US",
		)
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = CartService().create(payload)
			loaded_reference, loaded_quotation = CartService().retrieve(reference.cart_id)

		self.assertRegex(reference.cart_id, r"^cart_[0-9a-f]{32}$")
		self.assertEqual(reference.owner_user, None)
		self.assertEqual(reference.quotation, quotation.name)
		self.assertEqual(loaded_reference.name, reference.name)
		self.assertEqual(loaded_quotation.name, quotation.name)
		self.assertEqual(quotation.docstatus, 0)
		self.assertEqual(quotation.order_type, "Shopping Cart")
		self.assertEqual(quotation.party_name, self.masters.customer)
		self.assertEqual(quotation.contact_email, "guest@example.com")
		self.assertEqual(quotation.items, [])

		cart = CartSerializer().serialize(reference, quotation)
		self.assertEqual(cart["id"], reference.cart_id)
		self.assertEqual(cart["currency_code"], "usd")
		self.assertEqual(cart["region_id"], "reg_test")
		self.assertEqual(cart["sales_channel_id"], "sc_test")
		self.assertEqual(cart["metadata"], {"source": "test"})
		self.assertEqual(cart["total"], 0)

	def test_updates_core_fields_under_lock(self) -> None:
		configuration = {
			**self.masters.configuration,
			"regions": {
				"reg_test": {},
				"reg_other": {"territory": "All Territories"},
			},
		}
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			reference, _ = CartService().create(StoreCreateCart(metadata={"keep": True, "remove": True}))
			with patch.object(CartAccess, "_lock_row", side_effect=CartAccess._lock_row) as lock_row:
				reference, quotation = CartService().update(
					reference.cart_id,
					StoreUpdateCart(
						region_id="reg_other",
						email="updated@example.com",
						locale="th-TH",
						metadata={"remove": None, "new": 1},
					),
				)

		self.assertEqual(
			[locked.args for locked in lock_row.call_args_list],
			[
				("Ceto Cart Reference", reference.cart_id),
				("Quotation", quotation.name),
			],
		)
		self.assertEqual(reference.region_id, "reg_other")
		self.assertEqual(reference.locale, "th-TH")
		self.assertEqual(quotation.contact_email, "updated@example.com")
		self.assertEqual(
			CartSerializer().serialize(reference, quotation)["metadata"], {"keep": True, "new": 1}
		)

	def test_claimed_cart_is_hidden_from_other_users(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_create_user() as owner:
				reference, _ = CartService().create(StoreCreateCart())
				self.assertEqual(reference.owner_user, owner)
			with self.set_create_user():
				with self.assertRaisesRegex(RouteNotFoundError, "Cart not found"):
					CartService().retrieve(reference.cart_id)
			with self.set_user(owner):
				CartService().retrieve(reference.cart_id)

	def test_rejects_unknown_region_and_deferred_operations(self) -> None:
		configuration = {**self.masters.configuration, "regions": {"reg_test": {}}}
		with self.set_conf(ceto_cart=configuration), self.set_user("Guest"):
			with self.assertRaisesRegex(InvalidDataError, "Unknown cart region"):
				CartService().create(StoreCreateCart(region_id="reg_missing"))
			with self.assertRaisesRegex(InvalidDataError, "country_code is required"):
				CartService().create(
					StoreCreateCart(
						items=[StoreAddCartLineItem(variant_id=self.masters.item, quantity=1)],
						shipping_address={"first_name": "X"},
					)
				)

	def test_selects_requested_response_fields(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = CartService().create(StoreCreateCart(email="fields@example.com"))
		cart = CartSerializer().serialize(reference, quotation, fields="id,email")
		self.assertEqual(cart, {"id": reference.cart_id, "email": "fields@example.com"})
		with self.assertRaisesRegex(InvalidDataError, "Unknown cart field"):
			CartSerializer().serialize(reference, quotation, fields="id,secret")
