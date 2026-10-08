"""Targeted boundary hardening for the store surfaces.

The per-surface suites pin each route's own contract; these tests pin the
cross-cutting boundaries their isolation cannot exercise:

- a lost optimistic race on a real store write translates as
  ``400 invalid_data`` at the router (``frappe.TimestampMismatchError``
  rides the ``frappe.ValidationError`` family) and the request rolls back
  whole — the profile or book entry keeps its committed state;
- a disabled identity is ``401 unauthorized`` on every ``/me`` route —
  session or previously issued bearer — and the refusal performs none of
  the route's work, notably no destructive address delete;
- a claimed cart's settle failure rolls back to the settle savepoint while
  keeping the claim: the cart stays owned by the customer who claimed it
  and completes on the retry;
- a duplicate registration identity — the pre-check refusal and a
  registration insert that loses the concurrent race behind it — renders
  the identical stable ``400 invalid_data`` duplicate body at the router,
  leaving nothing half-registered.
"""

import uuid
from unittest.mock import patch

import frappe

from ceto.services.auth.tokens import authenticate_bearer_token, create_customer_token
from ceto.services.customers.addresses import book_names, create_address
from ceto.services.customers.creation import create_customer_profile
from ceto.tests.data.bootstrap_test_master_data import TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD
from ceto.tests.data.cart_test_data import make_customer_with_user
from ceto.tests.data.customer_test_data import new_identity
from ceto.tests.integration.base import IntegrationTestBase
from ceto.types.http.store.customers import StoreCreateCustomerAddress

_HOME = {"address_1": "1 Harbor Way", "city": "Portland", "country_code": "us"}


class TestProfileRaceTranslation(IntegrationTestBase):
	def test_a_lost_profile_race_translates_to_invalid_data_and_rolls_back(self) -> None:
		"""The TimestampMismatch API boundary on the real update route."""
		email = new_identity("journey-race")
		identity, reference = create_customer_profile(email, first_name="Aria", last_name="Stone")
		frappe.db.commit()  # nosemgrep - the committed chain the race must not corrupt
		before = {
			"contact": frappe.db.get_value("Contact", identity.contact, "modified"),
			"customer": frappe.db.get_value("Customer", identity.customer, "modified"),
			"reference": frappe.db.get_value("Ceto Customer Reference", reference.name, "modified"),
		}
		real_get_doc = frappe.get_doc
		raced = []

		def race_the_contact_load(*args, **kwargs):
			doc = real_get_doc(*args, **kwargs)
			if not raced and args[:2] == ("Contact", identity.contact):
				raced.append(doc.name)
				# A concurrent writer lands between the route's read and save.
				frappe.db.set_value("Contact", doc.name, "company_name", "Raced In")
			return doc

		with patch("frappe.get_doc", side_effect=race_the_contact_load):
			response = self._dispatch_with_hook(
				"POST", "/ceto/store/customers/me", {"last_name": "Ryn"}, token=create_customer_token(email)
			)

		self.assertEqual(response.status_code, 400, response.get_json())
		self.assertEqual(response.get_json()["type"], "invalid_data")
		# The router rolled the whole request back: the update's writes and
		# the racing write are gone, and the committed chain stands.
		self.assertEqual(
			{
				"contact": frappe.db.get_value("Contact", identity.contact, "modified"),
				"customer": frappe.db.get_value("Customer", identity.customer, "modified"),
				"reference": frappe.db.get_value("Ceto Customer Reference", reference.name, "modified"),
			},
			before,
		)
		profile = frappe.db.get_value(
			"Contact", identity.contact, ["first_name", "last_name", "company_name"], as_dict=True
		)
		self.assertEqual(
			(profile.first_name, profile.last_name, profile.company_name), ("Aria", "Stone", None)
		)
		self.assertEqual(frappe.db.get_value("Customer", identity.customer, "customer_name"), "Aria Stone")

	def test_a_lost_address_race_translates_to_invalid_data_and_rolls_back(self) -> None:
		"""The same boundary on the address book's write path."""
		email = new_identity("journey-addr-race")
		identity, _reference = create_customer_profile(email)
		create_address(email, StoreCreateCustomerAddress(**_HOME))
		address_id = book_names(identity.customer)[0]
		frappe.db.commit()  # nosemgrep - the committed entry the race must not corrupt
		before = frappe.db.get_value("Address", address_id, ["modified", "city"], as_dict=True)
		real_get_doc = frappe.get_doc

		def race_the_address_load(*args, **kwargs):
			doc = real_get_doc(*args, **kwargs)
			if args[:2] == ("Address", address_id):
				# A concurrent writer lands between the route's read and save.
				frappe.db.set_value("Address", doc.name, "city", "Raced In")
			return doc

		with patch("frappe.get_doc", side_effect=race_the_address_load):
			response = self._dispatch_with_hook(
				"POST",
				f"/ceto/store/customers/me/addresses/{address_id}",
				{"city": "Austin"},
				token=create_customer_token(email),
			)

		self.assertEqual(response.status_code, 400, response.get_json())
		self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(
			frappe.db.get_value("Address", address_id, ["modified", "city"], as_dict=True), before
		)


class TestMeIdentityBoundaries(IntegrationTestBase):
	def test_a_disabled_session_is_unauthorized_on_every_me_route(self) -> None:
		"""The Frappe permission boundary: a disabled identity owns nothing.

		Every ``/me`` route refuses the disabled session with the same
		``401 unauthorized`` mask — and performs none of the route's work:
		the destructive delete subtest must leave the entry in the book.
		"""
		email = new_identity("journey-disabled")
		identity, _reference = create_customer_profile(email, first_name="Aria", last_name="Stone")
		create_address(email, StoreCreateCustomerAddress(**_HOME))
		address_id = book_names(identity.customer)[0]
		frappe.db.set_value("User", email, "enabled", 0)
		frappe.db.commit()  # nosemgrep - the disabled state every subtest refuses against

		routes = (
			("GET", "/ceto/store/customers/me", None),
			("POST", "/ceto/store/customers/me", {"last_name": "Vale"}),
			("GET", "/ceto/store/customers/me/addresses", None),
			("POST", "/ceto/store/customers/me/addresses", dict(_HOME, address_1="9 Elsewhere")),
			("GET", f"/ceto/store/customers/me/addresses/{address_id}", None),
			("POST", f"/ceto/store/customers/me/addresses/{address_id}", {"city": "Austin"}),
			("DELETE", f"/ceto/store/customers/me/addresses/{address_id}", None),
		)
		for method, path, payload in routes:
			with self.subTest(route=f"{method} {path}"):
				with self.set_user(email):
					response = self._dispatch(method, path, payload)
				self.assertEqual(response.status_code, 401, response.get_json())
				self.assertEqual(response.get_json()["type"], "unauthorized")

		# Nothing moved: the book keeps its entry, no profile write landed.
		self.assertEqual(book_names(identity.customer), [address_id])
		self.assertEqual(frappe.db.get_value("Contact", identity.contact, "last_name"), "Stone")
		self.assertEqual(frappe.db.get_value("Customer", identity.customer, "customer_name"), "Aria Stone")

	def test_a_previously_issued_bearer_never_authenticates_a_disabled_identity(self) -> None:
		"""The auth hook refuses before the router: Frappe renders the 401."""
		email = new_identity("journey-bearer-disabled")
		create_customer_profile(email)
		token = create_customer_token(email)
		frappe.db.set_value("User", email, "enabled", 0)
		frappe.db.commit()  # nosemgrep - the disabled state the token refuses against

		request = self._request("GET", "/ceto/store/customers/me", token=token)
		with self.set_request(request), self.set_user("Guest"):
			with self.assertRaises(frappe.AuthenticationError):
				authenticate_bearer_token()


class TestClaimedSettleRollback(IntegrationTestBase):
	def test_a_claimed_settle_failure_keeps_the_cart_claimed_and_open(self) -> None:
		"""The settle savepoint must not unwind the claim that preceded it.

		An expected placement validation failure is the pinned
		``OrderPlacementError`` refusal (a 200 union member) with the settle
		rolled back to its savepoint — and the cart stays owned by the
		customer who claimed it, still served to them and completable.
		"""
		email, customer = make_customer_with_user("journey-settle-claim")
		token = create_customer_token(email)
		cart_id = self._committed_guest_cart()
		claimed = self._dispatch_with_hook("POST", f"/ceto/store/carts/{cart_id}/customer", token=token)
		self.assertEqual(claimed.status_code, 200, claimed.get_json())
		frappe.db.commit()  # nosemgrep - the committed claim the settle rollback must not unwind

		with patch(
			"ceto.services.carts.completion.convert_quotation_to_sales_order",
			side_effect=frappe.ValidationError("Credit limit exceeded for customer"),
		):
			with self.set_user(email):
				response = self._dispatch("POST", f"/ceto/store/carts/{cart_id}/complete", {})

		self.assertEqual(response.status_code, 200, response.get_json())
		body = response.get_json()
		self.assertEqual(set(body), {"type", "cart", "error"})
		self.assertEqual(body["type"], "cart")
		self.assertEqual(body["error"]["name"], "OrderPlacementError")
		self.assertEqual(body["error"]["type"], "order_placement_error")
		self.assertEqual(body["cart"]["id"], cart_id)
		# The claim survived the savepoint rollback and the cart is open.
		self.assertEqual(
			frappe.db.get_value(
				"Ceto Cart Reference", cart_id, ["owner_user", "owner_customer"], as_dict=True
			),
			{"owner_user": email, "owner_customer": customer},
		)
		quotation = frappe.db.get_value("Ceto Cart Reference", cart_id, "quotation")
		self.assertEqual(frappe.db.get_value("Quotation", quotation, "docstatus"), 0)
		self.assertIsNone(frappe.db.get_value("Ceto Order Reference", {"cart_id": cart_id}))

		served = self._dispatch_with_hook("GET", f"/ceto/store/carts/{cart_id}?fields=id", token=token)
		self.assertEqual(served.status_code, 200, served.get_json())

		# The retry places the order for the claiming customer.
		completed = self._dispatch_with_hook("POST", f"/ceto/store/carts/{cart_id}/complete", {}, token=token)
		self.assertEqual(completed.status_code, 200, completed.get_json())
		self.assertEqual(completed.get_json()["type"], "order")
		self.assertEqual(completed.get_json()["order"]["customer_id"], customer)

	def _committed_guest_cart(self) -> str:
		"""A checkout-ready committed guest cart, temporaries cleaned up."""
		self.addCleanup(self.masters.discard_committed_cart_temporaries)
		with self.set_user("Guest"):
			created = self._dispatch("POST", "/ceto/store/carts?fields=id", {"email": "guest@example.com"})
			self.assertEqual(created.status_code, 200, created.get_json())
			cart_id = created.get_json()["cart"]["id"]
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
						"address_1": "1 Completion Way",
						"city": "Bangkok",
						"country_code": "th",
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
			frappe.db.commit()  # nosemgrep - the cart must survive request rollbacks
		return cart_id


class TestRegistrationIdentityConflicts(IntegrationTestBase):
	def test_a_duplicate_registration_renders_the_stable_duplicate_body(self) -> None:
		"""The pre-check refusal is a 400 client refusal, not a storage 500."""
		response = self._dispatch(
			"POST",
			"/ceto/auth/customer/emailpass/register",
			{"email": TEST_CUSTOMER, "password": TEST_CUSTOMER_PASSWORD},
			publishable_key=None,
		)

		body = self._assert_error(response, 400, "invalid_data")
		self.assertEqual(body["message"], f"Customer {TEST_CUSTOMER} is already registered")

	def test_a_lost_registration_race_converges_on_the_identical_refusal(self) -> None:
		"""The production branch behind the registration pre-check.

		When a concurrent registration inserts the identity between the
		pre-check and the insert, the loser converges on the identical
		duplicate refusal — the same stable ``400 invalid_data`` body the
		pre-check renders — and leaves nothing half-registered behind.
		"""
		email = f"ceto.race.{uuid.uuid4().hex[:8]}@example.com"
		with patch(
			"ceto.services.auth.providers.emailpass.create_registration_identity",
			side_effect=frappe.DuplicateEntryError,
		):
			response = self._dispatch(
				"POST",
				"/ceto/auth/customer/emailpass/register",
				{"email": email, "password": TEST_CUSTOMER_PASSWORD},
				publishable_key=None,
			)

		body = self._assert_error(response, 400, "invalid_data")
		self.assertEqual(body["message"], f"Customer {email} is already registered")
		# The refusal rolled the whole request back: no half-registered
		# identity can survive a lost race.
		self.assertFalse(frappe.db.exists("User", email))
