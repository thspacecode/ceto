import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.carts.quotation import CartService
from ceto.services.carts.serialization import CartSerializer
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart, StoreUpdateCart

SHIPPING = {
	"first_name": "Aria",
	"last_name": "Stone",
	"phone": "+1 555 0100",
	"address_1": "1 Harbor Way",
	"address_2": "Suite 3",
	"city": "Portland",
	"province": "Oregon",
	"postal_code": "97201",
	"country_code": "us",
}

BILLING = {
	"first_name": "Aria",
	"last_name": "Stone",
	"company": "Stone Co",
	"address_1": "2 Market Street",
	"city": "Portland",
	"postal_code": "97205",
	"country_code": "US",
}


class TestCartAddresses(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		if not frappe.db.exists("Address Template", {"is_default": 1}):
			frappe.get_doc(
				{
					"doctype": "Address Template",
					"country": "United States",
					"is_default": 1,
					"template": "{{ address_line1 }}\n{{ city }}\n{{ country }}",
				}
			).insert(ignore_permissions=True)
		self.masters = CartTestData()

	def _create_cart(self, payload: StoreCreateCart | None = None):
		return CartService().create(payload or StoreCreateCart())

	def test_create_cart_with_object_addresses(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart(
				StoreCreateCart(shipping_address=SHIPPING, billing_address=BILLING)
			)

			self.assertTrue(quotation.shipping_address_name)
			self.assertTrue(quotation.customer_address)
			shipping = frappe.get_doc("Address", quotation.shipping_address_name)
			billing = frappe.get_doc("Address", quotation.customer_address)
			self.assertEqual(shipping.address_title, f"Cart {reference.cart_id}")
			self.assertEqual(shipping.address_type, "Shipping")
			self.assertEqual(billing.address_type, "Billing")
			self.assertEqual(shipping.address_line1, "1 Harbor Way")
			self.assertEqual(shipping.city, "Portland")
			self.assertEqual(shipping.state, "Oregon")
			self.assertEqual(shipping.pincode, "97201")
			self.assertEqual(shipping.country, "United States")
			self.assertEqual(shipping.phone, "+1 555 0100")
			self.assertEqual(billing.country, "United States")
			# Cart-scoped: linked only to the Quotation and its cart-unique
			# guest customer (required by ERPNext party validation).
			self.assertEqual(
				[(link.link_doctype, link.link_name) for link in shipping.links],
				[
					("Customer", quotation.party_name),
					("Quotation", quotation.name),
				],
			)
			# ERPNext refreshed the display snapshots on save.
			self.assertIn("1 Harbor Way", quotation.shipping_address)
			self.assertIn("2 Market Street", quotation.address_display)

	def test_serialized_cart_addresses(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart(
				StoreCreateCart(shipping_address=SHIPPING, billing_address=BILLING)
			)
			cart = CartSerializer().serialize(reference, quotation)
			self.assertEqual(cart["shipping_address"]["id"], quotation.shipping_address_name)
			self.assertEqual(cart["shipping_address"]["address_1"], "1 Harbor Way")
			self.assertEqual(cart["shipping_address"]["address_2"], "Suite 3")
			self.assertEqual(cart["shipping_address"]["city"], "Portland")
			self.assertEqual(cart["shipping_address"]["province"], "Oregon")
			self.assertEqual(cart["shipping_address"]["postal_code"], "97201")
			self.assertEqual(cart["shipping_address"]["country_code"], "us")
			self.assertEqual(cart["shipping_address"]["phone"], "+1 555 0100")
			self.assertEqual(cart["billing_address"]["id"], quotation.customer_address)
			self.assertEqual(cart["billing_address"]["country_code"], "us")
			self.assertNotEqual(cart["shipping_address"]["id"], cart["billing_address"]["id"])

	def test_update_and_replace_addresses(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart(
				StoreCreateCart(shipping_address=SHIPPING, billing_address=BILLING)
			)
			original_shipping = quotation.shipping_address_name

			reference, quotation = CartService().update(
				reference.cart_id,
				StoreUpdateCart(
					shipping_address={**SHIPPING, "address_1": "9 New Road", "city": "Austin"},
					billing_address=None,
				),
			)

			self.assertNotEqual(quotation.shipping_address_name, original_shipping)
			self.assertEqual(quotation.customer_address, None)
			shipping = frappe.get_doc("Address", quotation.shipping_address_name)
			self.assertEqual(shipping.address_line1, "9 New Road")
			self.assertEqual(shipping.city, "Austin")
			# The replaced/cleared cart-scoped temporaries are cleaned up.
			self.assertFalse(frappe.db.exists("Address", original_shipping))

	def test_id_form_reuses_own_cart_address(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart(
				StoreCreateCart(shipping_address=SHIPPING, billing_address=BILLING)
			)
			# Reuse the cart's billing address as its shipping address by ID.
			reference, quotation = CartService().update(
				reference.cart_id,
				StoreUpdateCart(shipping_address=quotation.customer_address),
			)
			self.assertEqual(quotation.shipping_address_name, quotation.customer_address)

	def test_id_form_rejects_foreign_addresses(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			_, other_quotation = self._create_cart(StoreCreateCart(shipping_address=SHIPPING))
			reference, _ = self._create_cart()

			with self.assertRaises(InvalidDataError):
				CartService().update(
					reference.cart_id,
					StoreUpdateCart(shipping_address=other_quotation.shipping_address_name),
				)
			# Unknown IDs fail the same way instead of leaking existence.
			with self.assertRaises(InvalidDataError):
				CartService().update(
					reference.cart_id,
					StoreUpdateCart(billing_address="does-not-exist"),
				)

	def test_invalid_country_code_rejected(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			with self.assertRaises(InvalidDataError):
				self._create_cart(StoreCreateCart(shipping_address={**SHIPPING, "country_code": "xx"}))

	def test_address_id_form_accepts_claimed_customer_address(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration), self.set_user("Guest"):
			reference, quotation = self._create_cart()
			customer_address = frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": "Claimed Customer HQ",
					"address_type": "Billing",
					"address_line1": "7 Claimed Lane",
					"city": "Portland",
					"country": "United States",
					"links": [{"link_doctype": "Customer", "link_name": self.masters.customer}],
				}
			)
			customer_address.flags.ignore_permissions = True
			customer_address.insert()
			reference.owner_customer = self.masters.customer
			reference.save(ignore_permissions=True)

			reference, quotation = CartService().update(
				reference.cart_id,
				StoreUpdateCart(billing_address=customer_address.name),
			)
			self.assertEqual(quotation.customer_address, customer_address.name)
