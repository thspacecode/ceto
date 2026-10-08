"""The registered-customer purchase journey, end to end.

One test walks the whole storefront story the per-surface suites pin in
pieces, through the real router on the test site: register (identity plus
single-purpose registration token), create the customer profile,
authenticate with the registered credentials, read and update the profile,
create/retrieve/update/list the address book — deleting the unused entry at
its safe point — build a guest cart with an item, a temporary shipping
address and a shipping method, claim the cart (the temporary is copied into
the customer's book), attach the owned address by id, complete the cart,
replay the completion, and delete the placed order's shipping address.

The assertions pin the cross-surface semantics no single surface can prove:
the stable ``cus_…`` id behind every response, the claimed cart's ownership
mask, the embedded order customer (the customers contract's identity beside
the historical ERPNext ``customer_id``) and the linked-address retention/
unlink split — an unused entry is destroyed, while an entry a placed order
still links is retained for the order but removed from the book.

Failed requests roll back the open transaction like real failed HTTP
requests, so every stage commits before the next error-bearing request —
mirroring production, where each stage was its own committed request.
"""

import re
import uuid

import frappe

from ceto.services.auth.tokens import decode_customer_token
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER_PASSWORD
from ceto.tests.integration.base import IntegrationTestBase

CUS_ID = re.compile(r"^cus_[0-9a-f]{32}$")
ORDER_ID = re.compile(r"^order_[0-9a-f]{32}$")
ADDR_ID = re.compile(r"^addr_[0-9a-f]{32}$")


class TestCustomerPurchaseJourney(IntegrationTestBase):
	def test_the_registered_customer_walks_register_to_replayed_order(self) -> None:
		email = f"ceto.journey.{uuid.uuid4().hex[:8]}@example.com"

		# 1. Register: the enabled Website User identity and its
		# single-purpose registration token, password stored hashed.
		registered = self._dispatch(
			"POST",
			"/ceto/auth/customer/emailpass/register",
			{"email": email, "password": TEST_CUSTOMER_PASSWORD},
		)
		self.assertEqual(registered.status_code, 200, registered.get_json())
		registration_token = registered.get_json()["token"]
		self.assertEqual(decode_customer_token(registration_token, purpose="registration")["sub"], email)
		self.assertEqual(
			frappe.db.get_value("User", email, ["enabled", "user_type"], as_dict=True),
			{"enabled": 1, "user_type": "Website User"},
		)

		# 2. Create the customer profile with the registration token.
		created = self._dispatch(
			"POST",
			"/ceto/store/customers",
			{"first_name": "Aria", "last_name": "Stone", "phone": "+66 2 123 4567"},
			token=registration_token,
		)
		self.assertEqual(created.status_code, 200, created.get_json())
		profile = created.get_json()["customer"]
		customer_id = profile["id"]
		self.assertRegex(customer_id, CUS_ID)
		self.assertEqual(profile["email"], email)
		self.assertEqual(profile["first_name"], "Aria")
		self.assertEqual(profile["last_name"], "Stone")
		self.assertEqual(profile["phone"], "+66 2 123 4567")
		self.assertEqual(profile["addresses"], [])
		frappe.db.commit()  # nosemgrep - the committed profile behind later error requests

		# 3. Authenticate with the registered credentials.
		auth_response, login_manager = self._dispatch_authentication(
			"/ceto/auth/customer/emailpass", {"email": email, "password": TEST_CUSTOMER_PASSWORD}
		)
		self.assertEqual(auth_response.status_code, 200, auth_response.get_json())
		self.assertEqual(login_manager.user, email)
		auth_token = auth_response.get_json()["token"]
		self.assertEqual(decode_customer_token(auth_token)["sub"], email)

		# 4. The authenticated profile reads back through the bearer flow.
		me = self._dispatch_with_hook(
			"GET", "/ceto/store/customers/me?fields=id,email,first_name,last_name,phone", token=auth_token
		)
		self.assertEqual(me.status_code, 200, me.get_json())
		self.assertEqual(
			me.get_json()["customer"],
			{
				"id": customer_id,
				"email": email,
				"first_name": "Aria",
				"last_name": "Stone",
				"phone": "+66 2 123 4567",
			},
		)

		# 5. The profile update moves only the supplied columns and keeps
		# the identity: the same cus_ id answers after every change.
		updated = self._dispatch_with_hook(
			"POST",
			"/ceto/store/customers/me?fields=id,email,first_name,last_name,phone",
			{"last_name": "Vale", "phone": "+66 2 987 6543", "metadata": {"tier": "gold"}},
			token=auth_token,
		)
		self.assertEqual(updated.status_code, 200, updated.get_json())
		self.assertEqual(
			updated.get_json()["customer"],
			{
				"id": customer_id,
				"email": email,
				"first_name": "Aria",
				"last_name": "Vale",
				"phone": "+66 2 987 6543",
			},
		)

		# 6. The address book: two created entries, then retrieve, update,
		# list — and the safe-point deletion of the unused entry.
		home = self._dispatch_with_hook(
			"POST",
			"/ceto/store/customers/me/addresses",
			{
				"address_name": "Home",
				"address_1": "1 Harbor Way",
				"city": "Portland",
				"country_code": "us",
				"postal_code": "97205",
				"is_default_shipping": True,
			},
			token=auth_token,
		)
		self.assertEqual(home.status_code, 200, home.get_json())
		home_id = home.get_json()["customer"]["addresses"][-1]["id"]
		self.assertRegex(home_id, ADDR_ID)

		vault = self._dispatch_with_hook(
			"POST",
			"/ceto/store/customers/me/addresses",
			{"address_name": "Vault", "address_1": "9 Vault St", "city": "Salem", "country_code": "us"},
			token=auth_token,
		)
		self.assertEqual(vault.status_code, 200, vault.get_json())
		vault_id = vault.get_json()["customer"]["addresses"][-1]["id"]

		retrieved = self._dispatch_with_hook(
			"GET", f"/ceto/store/customers/me/addresses/{vault_id}", token=auth_token
		)
		self.assertEqual(retrieved.status_code, 200, retrieved.get_json())
		# The book entry names its owner by the contract identity, not the
		# ERPNext Customer (recorded decision 5).
		self.assertEqual(retrieved.get_json()["address"]["customer_id"], customer_id)
		self.assertEqual(retrieved.get_json()["address"]["city"], "Salem")

		moved = self._dispatch_with_hook(
			"POST",
			f"/ceto/store/customers/me/addresses/{vault_id}",
			{"city": "Austin"},
			token=auth_token,
		)
		self.assertEqual(moved.status_code, 200, moved.get_json())
		reread = self._dispatch_with_hook(
			"GET", f"/ceto/store/customers/me/addresses/{vault_id}", token=auth_token
		)
		self.assertEqual(reread.get_json()["address"]["city"], "Austin")

		listed = self._dispatch_with_hook("GET", "/ceto/store/customers/me/addresses", token=auth_token)
		self.assertEqual(listed.status_code, 200, listed.get_json())
		book = listed.get_json()
		self.assertEqual([entry["id"] for entry in book["addresses"]], [home_id, vault_id])
		self.assertEqual(book["count"], 2)

		deleted = self._dispatch_with_hook(
			"DELETE", f"/ceto/store/customers/me/addresses/{vault_id}", token=auth_token
		)
		self.assertEqual(deleted.status_code, 200, deleted.get_json())
		body = deleted.get_json()
		self.assertEqual((body["id"], body["object"], body["deleted"]), (vault_id, "address", True))
		self.assertEqual([entry["id"] for entry in body["parent"]["addresses"]], [home_id])
		# No placed order links it: the safe-point delete destroys the entry.
		self.assertIsNone(frappe.db.exists("Address", vault_id))
		after = self._dispatch_with_hook("GET", "/ceto/store/customers/me/addresses", token=auth_token)
		self.assertEqual([entry["id"] for entry in after.get_json()["addresses"]], [home_id])
		frappe.db.commit()  # nosemgrep - the committed book behind later error requests

		# 7. The guest cart: created for the guest party with an item, a
		# cart-scoped temporary shipping address and a shipping method.
		self.addCleanup(self.masters.discard_committed_cart_temporaries)
		with self.set_user("Guest"):
			cart_response = self._dispatch("POST", "/ceto/store/carts", {"email": "guest@example.com"})
			self.assertEqual(cart_response.status_code, 200, cart_response.get_json())
			cart_id = cart_response.get_json()["cart"]["id"]
			added = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/line-items",
				{"variant_id": self.masters.item, "quantity": 1},
			)
			self.assertEqual(added.status_code, 200, added.get_json())
			addressed = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}",
				{
					"shipping_address": {
						"address_1": "2 Checkout Lane",
						"city": "Bangkok",
						"country_code": "th",
						"phone": "+66 2 000 0000",
					}
				},
			)
			self.assertEqual(addressed.status_code, 200, addressed.get_json())
			shipped = self._dispatch(
				"POST",
				f"/ceto/store/carts/{cart_id}/shipping-methods",
				{"option_id": self.masters.flat_rate_rule},
			)
			self.assertEqual(shipped.status_code, 200, shipped.get_json())
			guest_cart = shipped.get_json()["cart"]
		self.assertIsNone(guest_cart["customer_id"])
		temporary_id = guest_cart["shipping_address"]["id"]
		frappe.db.commit()  # nosemgrep - the committed guest cart the claim moves

		# 8. Claim: the guest cart moves to the customer; the temporary
		# shipping address is copied into their book and linked instead.
		claimed = self._dispatch_with_hook("POST", f"/ceto/store/carts/{cart_id}/customer", token=auth_token)
		self.assertEqual(claimed.status_code, 200, claimed.get_json())
		claimed_cart = claimed.get_json()["cart"]
		reference = frappe.db.get_value(
			"Ceto Cart Reference", cart_id, ["owner_user", "owner_customer", "quotation"], as_dict=True
		)
		self.assertEqual(reference.owner_user, email)
		self.assertEqual(claimed_cart["customer_id"], reference.owner_customer)
		quotation_shipping = frappe.db.get_value("Quotation", reference.quotation, "shipping_address_name")
		self.assertEqual(quotation_shipping, claimed_cart["shipping_address"]["id"])
		self.assertNotEqual(quotation_shipping, temporary_id)
		self.assertIsNone(frappe.db.exists("Address", temporary_id))
		copied_id = quotation_shipping
		book_after_claim = self._dispatch_with_hook(
			"GET", "/ceto/store/customers/me/addresses?fields=id,city", token=auth_token
		)
		self.assertEqual(
			book_after_claim.get_json()["addresses"],
			[{"id": home_id, "city": "Portland"}, {"id": copied_id, "city": "Bangkok"}],
		)
		frappe.db.commit()  # nosemgrep - the committed claim behind later error requests

		# 9. Ownership: the claimed cart is masked from the guest it came
		# from and served to its owner.
		with self.set_user("Guest"):
			masked = self._dispatch("GET", f"/ceto/store/carts/{cart_id}")
		self.assertEqual(masked.status_code, 404)
		self.assertEqual(masked.get_json()["type"], "not_found")
		owned = self._dispatch_with_hook("GET", f"/ceto/store/carts/{cart_id}", token=auth_token)
		self.assertEqual(owned.status_code, 200, owned.get_json())
		self.assertEqual(owned.get_json()["cart"]["customer_id"], reference.owner_customer)

		# 10. The owned address attaches by id: the claim copy stays in the
		# book while the cart ships to the customer's own entry.
		attached = self._dispatch_with_hook(
			"POST",
			f"/ceto/store/carts/{cart_id}?fields=id,shipping_address",
			{"shipping_address": home_id},
			token=auth_token,
		)
		self.assertEqual(attached.status_code, 200, attached.get_json())
		self.assertEqual(attached.get_json()["cart"]["shipping_address"]["id"], home_id)
		self.assertEqual(
			frappe.db.get_value("Quotation", reference.quotation, "shipping_address_name"), home_id
		)
		still_booked = self._dispatch_with_hook(
			"GET", "/ceto/store/customers/me/addresses?fields=id", token=auth_token
		)
		self.assertEqual(
			[entry["id"] for entry in still_booked.get_json()["addresses"]], [home_id, copied_id]
		)

		# 11. Complete: the placed order carries the claim's identity — the
		# checkout contact moved to the customer, customer_id keeps the
		# historical ERPNext mapping and the embedded customer is exactly
		# the customers contract's identity with its book.
		completed = self._dispatch_with_hook(
			"POST", f"/ceto/store/carts/{cart_id}/complete", {}, token=auth_token
		)
		self.assertEqual(completed.status_code, 200, completed.get_json())
		completion = completed.get_json()
		self.assertEqual(completion["type"], "order")
		order = completion["order"]
		self.assertRegex(order["id"], ORDER_ID)
		self.assertEqual(order["email"], email)
		self.assertEqual(order["customer_id"], reference.owner_customer)
		embedded = order["customer"]
		self.assertEqual(embedded["id"], customer_id)
		self.assertEqual(embedded["email"], email)
		self.assertNotEqual(order["customer_id"], embedded["id"])
		self.assertEqual({entry["id"] for entry in embedded["addresses"]}, {home_id, copied_id})
		for entry in embedded["addresses"]:
			self.assertEqual(entry["customer_id"], customer_id)
		self.assertEqual(order["shipping_address"]["id"], home_id)
		self.assertEqual(len(order["items"]), 1)
		self.assertEqual(order["status"], "pending")
		order_reference = frappe.db.get_value(
			"Ceto Order Reference", order["id"], ["sales_order", "cart_id"], as_dict=True
		)
		self.assertEqual(order_reference.cart_id, cart_id)
		self.assertEqual(frappe.db.get_value("Sales Order", order_reference.sales_order, "docstatus"), 1)
		frappe.db.commit()  # nosemgrep - the placed order must survive later rollbacks

		# 12. Replay: the owner's repeats return the same placed order; the
		# completed cart is masked everywhere else.
		replayed = self._dispatch_with_hook(
			"POST", f"/ceto/store/carts/{cart_id}/complete", {}, token=auth_token
		)
		self.assertEqual(replayed.status_code, 200, replayed.get_json())
		self.assertEqual(replayed.get_json()["order"]["id"], order["id"])
		self.assertEqual(replayed.get_json()["order"]["customer"], embedded)
		self.assertEqual(frappe.db.count("Ceto Order Reference", {"cart_id": cart_id}), 1)
		with self.set_user("Guest"):
			foreign = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/complete", {})
		self.assertEqual(foreign.status_code, 404)
		self.assertEqual(foreign.get_json()["type"], "not_found")
		after_order = self._dispatch_with_hook("GET", f"/ceto/store/carts/{cart_id}", token=auth_token)
		self.assertEqual(after_order.status_code, 404)

		# 13. Retention and unlink: the placed order still links the
		# shipping address, so its delete is refused by the normal ERPNext
		# link check — the entry is retained for the order but leaves the
		# book (recorded decision 9).
		unlinked = self._dispatch_with_hook(
			"DELETE", f"/ceto/store/customers/me/addresses/{home_id}", token=auth_token
		)
		self.assertEqual(unlinked.status_code, 200, unlinked.get_json())
		self.assertEqual((unlinked.get_json()["id"], unlinked.get_json()["deleted"]), (home_id, True))
		self.assertEqual([entry["id"] for entry in unlinked.get_json()["parent"]["addresses"]], [copied_id])
		frappe.db.commit()  # nosemgrep - the committed unlink behind later error requests
		self.assertTrue(frappe.db.exists("Address", home_id))
		self.assertFalse(
			frappe.db.exists(
				"Dynamic Link",
				{
					"parenttype": "Address",
					"parent": home_id,
					"link_doctype": "Customer",
					"link_name": reference.owner_customer,
				},
			)
		)
		self.assertEqual(
			frappe.db.get_value("Sales Order", order_reference.sales_order, "shipping_address_name"),
			home_id,
		)
		gone = self._dispatch_with_hook(
			"GET", f"/ceto/store/customers/me/addresses/{home_id}", token=auth_token
		)
		self.assertEqual(gone.status_code, 404)
		self.assertEqual(gone.get_json()["type"], "not_found")
		final_book = self._dispatch_with_hook(
			"GET", "/ceto/store/customers/me/addresses?fields=id", token=auth_token
		)
		self.assertEqual([entry["id"] for entry in final_book.get_json()["addresses"]], [copied_id])

		# 14. The identity is intact behind the whole journey: the same
		# cus_ id, the profile columns of step 5 and the surviving book.
		final = self._dispatch_with_hook(
			"GET", "/ceto/store/customers/me?fields=id,email,first_name,last_name", token=auth_token
		)
		self.assertEqual(final.status_code, 200, final.get_json())
		self.assertEqual(
			final.get_json()["customer"],
			{"id": customer_id, "email": email, "first_name": "Aria", "last_name": "Vale"},
		)
