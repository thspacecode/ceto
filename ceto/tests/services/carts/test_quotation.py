from unittest.mock import patch

import frappe

from ceto.routing.exceptions import InvalidDataError, RouteNotFoundError
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart, StoreUpdateCart


class TestCartQuotation(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()

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
			with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as database_sql:
				reference, quotation = CartService().update(
					reference.cart_id,
					StoreUpdateCart(
						region_id="reg_other",
						email="updated@example.com",
						locale="th-TH",
						metadata={"remove": None, "new": 1},
					),
				)

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
			with self.assertRaisesRegex(InvalidDataError, "line items"):
				CartService().create(StoreCreateCart(items=[{"variant_id": "x", "quantity": 1}]))

	def test_selects_requested_response_fields(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = CartService().create(StoreCreateCart(email="fields@example.com"))
		cart = CartSerializer().serialize(reference, quotation, fields="id,email")
		self.assertEqual(cart, {"id": reference.cart_id, "email": "fields@example.com"})
		with self.assertRaisesRegex(InvalidDataError, "Unknown cart field"):
			CartSerializer().serialize(reference, quotation, fields="id,secret")
