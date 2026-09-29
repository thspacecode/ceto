import uuid

import frappe
from frappe.utils import today

from ceto.routing.exceptions import RouteNotFoundError, UnauthorizedError
from ceto.services.carts.claim import CartClaim
from ceto.services.carts.quotation import CartService
from ceto.tests.data.cart_test_data import ITEM_PRICE, TAX_RATE, CartTestData
from ceto.tests.testsuite import CetoTestSuite
from ceto.types.http.store.carts import (
	StoreAddCartLineItem,
	StoreCartAddressPayload,
	StoreCreateCart,
)

SHIPPING = {
	"first_name": "Aria",
	"last_name": "Stone",
	"phone": "+1 555 0100",
	"address_1": "1 Harbor Way",
	"city": "Portland",
	"province": "Oregon",
	"postal_code": "97201",
	"country_code": "us",
}


class TestCartClaim(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		# Shared, committed masters survive the error-path rollbacks
		# triggered by the router/handler in subtests below.
		self.masters = CartTestData.shared()
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000
		self.buyer = self._make_claiming_customer("buyer")
		self.other = self._make_claiming_customer("other")

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def _make_claiming_customer(self, label: str) -> tuple[str, str]:
		"""Create a Website User, its Customer and the linking Contact."""
		# Unique per test: guest carts commit, so claiming parties created in
		# earlier tests survive and must not collide.
		email = f"ceto.claim.{label}.{uuid.uuid4().hex[:8]}@example.com"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": f"Claim {label}",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": f"Claimed {label} {uuid.uuid4().hex[:8]}",
				"customer_type": "Individual",
				"customer_group": customer_group,
				"territory": "All Territories",
				"email_id": email,
			}
		)
		customer.flags.ignore_permissions = True
		customer.insert()
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": f"Claim {label}",
				"email_id": email,
				"user": email,
				"links": [{"link_doctype": "Customer", "link_name": customer.name}],
			}
		)
		contact.flags.ignore_permissions = True
		contact.insert()
		return email, customer.name

	def _guest_cart(self, with_line: bool = True, with_address: bool = False):
		payload = StoreCreateCart(email="guest@example.com")
		if with_address:
			payload.shipping_address = StoreCartAddressPayload.model_validate(SHIPPING)
		with self.set_user("Guest"):
			reference, _quotation = CartService().create(payload)
			if with_line:
				reference, _quotation, _mapping = CartService().add_line_item(
					reference.cart_id, StoreAddCartLineItem(variant_id=self.masters.item, quantity=2)
				)
		frappe.db.commit()
		with self.set_user("Guest"):
			return CartService().retrieve(reference.cart_id)

	def test_claims_guest_cart_for_authenticated_customer(self) -> None:
		email, customer = self.buyer
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, quotation = self._guest_cart(with_address=True)
				temporary_shipping = quotation.shipping_address_name

			with self.set_user(email):
				reference, quotation = CartClaim().claim(reference.cart_id)

			self.assertEqual(reference.owner_user, email)
			self.assertEqual(reference.owner_customer, customer)
			self.assertEqual(quotation.party_name, customer)
			self.assertEqual(quotation.contact_email, email)
			# Guest pricing was re-fetched for the customer by ERPNext and all
			# totals recalculated (2 x 100 + 10% tax).
			self.assertEqual(quotation.items[0].rate, ITEM_PRICE)
			self.assertEqual(quotation.total, 2 * ITEM_PRICE)
			self.assertAlmostEqual(quotation.grand_total, 2 * ITEM_PRICE * (1 + TAX_RATE / 100))
			# The guest-party temporary became a customer-owned copy and the
			# slot was relinked to it (Recorded Decision 4).
			self.assertFalse(frappe.db.exists("Address", temporary_shipping))
			shipping_name = frappe.db.get_value("Quotation", quotation.name, "shipping_address_name")
			self.assertNotEqual(shipping_name, temporary_shipping)
			shipping = frappe.get_doc("Address", shipping_name)
			self.assertEqual(shipping.address_line1, "1 Harbor Way")
			self.assertEqual(shipping.city, "Portland")
			self.assertEqual(
				[(link.link_doctype, link.link_name) for link in shipping.links],
				[("Customer", customer)],
			)

	def test_claim_copies_shared_temporary_once_for_both_slots(self) -> None:
		email, customer = self.buyer
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, quotation = self._guest_cart(with_address=True)
				temporary = quotation.shipping_address_name
				# ERPNext mirrors the shipping temporary into an empty billing
				# slot; reproduce that state explicitly.
				quotation.db_set("customer_address", temporary, notify=False)
				frappe.db.commit()

			with self.set_user(email):
				reference, quotation = CartClaim().claim(reference.cart_id)

			values = frappe.db.get_values(
				"Quotation",
				quotation.name,
				["customer_address", "shipping_address_name"],
				as_dict=True,
			)[0]
			copy = values.shipping_address_name
			self.assertEqual(values.customer_address, copy)
			self.assertNotEqual(copy, temporary)
			self.assertFalse(frappe.db.exists("Address", temporary))
			self.assertEqual(
				[link.link_name for link in frappe.get_doc("Address", copy).links],
				[customer],
			)

	def test_ambiguous_customer_link_is_unauthorized(self) -> None:
		email, _customer = self.buyer
		_, other_customer = self.other
		# A second Contact links the same user to another Customer.
		duplicate = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Ambiguous",
				"email_id": email,
				"user": email,
				"links": [{"link_doctype": "Customer", "link_name": other_customer}],
			}
		)
		duplicate.flags.ignore_permissions = True
		duplicate.insert()
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, _ = self._guest_cart()
			with self.set_user(email):
				with self.assertRaises(UnauthorizedError):
					CartClaim().claim(reference.cart_id)

	def test_claim_is_idempotent_for_same_owner(self) -> None:
		email, customer = self.buyer
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, _quotation = self._guest_cart()
			with self.set_user(email):
				first = CartClaim().claim(reference.cart_id)
				second = CartClaim().claim(reference.cart_id)

			self.assertEqual(first[0].name, second[0].name)
			self.assertEqual(second[0].owner_user, email)
			self.assertEqual(second[0].owner_customer, customer)
			self.assertEqual(second[1].party_name, customer)
			self.assertEqual(len(second[1].items), 1)

	def test_claim_keeps_customer_owned_address(self) -> None:
		email, customer = self.buyer
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, quotation = self._guest_cart()
			# Simulate a previously attached customer address.
			owned = frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": "Claimed HQ",
					"address_type": "Shipping",
					"address_line1": "9 Owner Way",
					"city": "Portland",
					"country": "United States",
					"links": [{"link_doctype": "Customer", "link_name": customer}],
				}
			)
			owned.flags.ignore_permissions = True
			owned.insert()
			quotation.db_set("shipping_address_name", owned.name, notify=False)
			frappe.db.commit()

			with self.set_user(email):
				reference, quotation = CartClaim().claim(reference.cart_id)

			self.assertEqual(quotation.shipping_address_name, owned.name)
			self.assertTrue(frappe.db.exists("Address", owned.name))

	def test_claim_preserves_sales_channel_price_list(self) -> None:
		email, customer = self.buyer
		# The claiming Customer has its own default price list with a much
		# higher rate; the cart must keep the sales-channel one.
		customer_price_list = f"Ceto Customer {uuid.uuid4().hex[:8]}"
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": customer_price_list,
				"selling": 1,
				"buying": 0,
				"enabled": 1,
				"currency": "USD",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": self.masters.item,
				"price_list": customer_price_list,
				"price_list_rate": 500,
				"currency": "USD",
				"valid_from": today(),
				"valid_upto": None,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", customer, "default_price_list", customer_price_list)

		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, _quotation = self._guest_cart()
			with self.set_user(email):
				reference, quotation = CartClaim().claim(reference.cart_id)

			self.assertEqual(quotation.selling_price_list, self.masters.price_list)
			self.assertEqual(quotation.currency, "USD")
			# Rate still comes from the sales-channel price list, not the
			# customer default (500).
			self.assertEqual(quotation.items[0].price_list_rate, ITEM_PRICE)
			self.assertEqual(quotation.items[0].rate, ITEM_PRICE)

	def test_claim_detaches_address_of_another_party(self) -> None:
		email, _customer = self.buyer
		_, other_customer = self.other
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, quotation = self._guest_cart()
				# An address owned by a third-party customer is neither the
				# claiming customer's nor this cart's temporary: it must be
				# detached, never copied or re-linked to the claimer.
				foreign = frappe.get_doc(
					{
						"doctype": "Address",
						"address_title": "Foreign HQ",
						"address_type": "Shipping",
						"address_line1": "7 Stranger Way",
						"city": "Portland",
						"country": "United States",
						"links": [{"link_doctype": "Customer", "link_name": other_customer}],
					}
				)
				foreign.flags.ignore_permissions = True
				foreign.insert()
				quotation.db_set("shipping_address_name", foreign.name, notify=False)
				frappe.db.commit()

				with self.set_user(email):
					reference, quotation = CartClaim().claim(reference.cart_id)

				self.assertNotEqual(
					frappe.db.get_value("Quotation", quotation.name, "shipping_address_name"),
					foreign.name,
				)
				# The address itself survives untouched for its real owner.
				self.assertTrue(frappe.db.exists("Address", foreign.name))
				foreign.reload()
				self.assertEqual(
					[(link.link_doctype, link.link_name) for link in foreign.links],
					[("Customer", other_customer)],
				)

	def test_unauthenticated_claim_is_rejected_without_mutation(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, quotation = self._guest_cart()
				with self.assertRaises(UnauthorizedError):
					CartClaim().claim(reference.cart_id)

			reference, quotation = CartService().retrieve(reference.cart_id)
			self.assertEqual(reference.owner_user, None)
			self.assertEqual(reference.owner_customer, None)
			self.assertEqual(quotation.party_name, self.masters.customer)

	def test_claim_without_customer_link_is_unauthorized(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, _ = self._guest_cart()
			with self.set_create_user():  # Website User without a Contact/Customer
				with self.assertRaises(UnauthorizedError):
					CartClaim().claim(reference.cart_id)

	def test_competing_owner_is_masked_and_keeps_ownership(self) -> None:
		owner_email, owner_customer = self.buyer
		other_email, _ = self.other
		with self.set_conf(ceto_cart=self.masters.configuration):
			with self.set_user("Guest"):
				reference, _ = self._guest_cart()
			with self.set_user(owner_email):
				CartClaim().claim(reference.cart_id)

			with self.set_user(other_email):
				with self.assertRaises(RouteNotFoundError):
					CartClaim().claim(reference.cart_id)

			# The original owner keeps the cart; the guest session lost access.
			with self.set_user(owner_email):
				reference, quotation = CartService().retrieve(reference.cart_id)
			self.assertEqual(reference.owner_user, owner_email)
			self.assertEqual(reference.owner_customer, owner_customer)
			self.assertEqual(quotation.party_name, owner_customer)
