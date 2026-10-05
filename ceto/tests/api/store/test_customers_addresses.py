"""Store Customer address-book endpoints (Phase 3: routes 4-8).

Pins the HTTP boundary of ``/store/customers/me/addresses`` on the test site:
the pinned response shapes (the projected entry, the paginated book envelope,
the parent customer, the fixed delete shape), the ``fields`` selector applied
after the write with the router rolling a failed selector back, the pinned
query refusals (unknown and deliberately dropped parameters) and the shared
gates — the publishable key first, then the router's session/bearer
authentication, with missing/foreign/disabled entries masked as the same
``404 not_found``. Error subtests rely on the router rolling the open
transaction back, so the identities and entries they must find are committed
first.
"""

import frappe

import ceto.api.routes
import ceto.api.store.customers
from ceto.api.store.customers import (
	create_customer_address,
	delete_customer_address,
	list_customer_addresses,
	retrieve_customer_address,
	update_customer_address,
)
from ceto.services.customers.addresses import book_names, create_address
from ceto.services.customers.creation import create_customer_profile
from ceto.tests.api.store.test_customers import CustomerAPITestBase
from ceto.types.http.store.customers import (
	StoreCreateCustomerAddress,
	StoreCustomer,
	StoreCustomerAddress,
)

_UNKNOWN_ADDRESS_ID = "addr_" + "0" * 32

_ADDRESS_GATES = (
	("GET", "/ceto/store/customers/me/addresses"),
	("POST", "/ceto/store/customers/me/addresses"),
	("GET", f"/ceto/store/customers/me/addresses/{_UNKNOWN_ADDRESS_ID}"),
	("POST", f"/ceto/store/customers/me/addresses/{_UNKNOWN_ADDRESS_ID}"),
	("DELETE", f"/ceto/store/customers/me/addresses/{_UNKNOWN_ADDRESS_ID}"),
)


class TestCustomerAddressAPI(CustomerAPITestBase):
	"""The five thin address handlers against the dispatched router."""

	def setUp(self) -> None:
		super().setUp()
		self.email = self._identity("addr-api")
		self.identity, self.reference = create_customer_profile(
			self.email, first_name="Aria", last_name="Stone"
		)
		frappe.db.commit()  # nosemgrep

	def _payload(self, **overrides) -> dict:
		values = {"address_1": "1 Harbor Way", "city": "Portland", "country_code": "us"}
		values.update(overrides)
		return values

	def _committed_entry(self, **overrides) -> str:
		"""Create one book entry through the service and commit it.

		Error subtests roll the open transaction back, so entries they must
		find are committed first — the profile suites' convention.
		"""
		create_address(self.email, StoreCreateCustomerAddress(**self._payload(**overrides)))
		name = book_names(self.identity.customer)[-1]
		frappe.db.commit()  # nosemgrep
		return name

	def _committed_peer_entry(self) -> str:
		email = self._identity("addr-peer")
		peer_identity, _peer_reference = create_customer_profile(email)
		create_address(
			peer_identity.user,
			StoreCreateCustomerAddress(address_1="9 Elsewhere", city="Salem", country_code="us"),
		)
		name = book_names(peer_identity.customer)[-1]
		frappe.db.commit()  # nosemgrep
		return name

	# ------------------------------------------------------------------ gate

	def test_endpoints_are_not_whitelisted(self):
		for endpoint in (
			list_customer_addresses,
			create_customer_address,
			retrieve_customer_address,
			update_customer_address,
			delete_customer_address,
		):
			self.assertNotIn(endpoint, frappe.whitelisted)
			self.assertFalse(hasattr(endpoint, "is_whitelisted"))

	def test_address_routes_require_authentication(self):
		with self.set_user("Guest"):
			for method, path in _ADDRESS_GATES:
				with self.subTest(method=method):
					payload = self._payload() if method == "POST" and path.endswith("addresses") else None
					response = self._dispatch(method, path, payload)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	def test_address_routes_require_a_configured_publishable_key(self):
		with self.set_user(self.email):
			for method, path in _ADDRESS_GATES:
				with self.subTest(method=method):
					response = self._dispatch(method, path, self._payload(), publishable_key=None)
					self.assertEqual(response.status_code, 401)
					self.assertEqual(response.get_json()["type"], "unauthorized")

	# ------------------------------------------------------------------ list

	def test_list_returns_the_pinned_paginated_book(self):
		home = self._committed_entry(address_name="Home")
		shore = self._committed_entry(address_1="2 Shore Road", city="Salem")

		with self.set_user(self.email):
			response = self._dispatch("GET", "/ceto/store/customers/me/addresses")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"addresses", "count", "offset", "limit"})
		self.assertEqual(body["count"], 2)
		self.assertEqual(body["offset"], 0)
		self.assertEqual(body["limit"], 20)
		self.assertEqual([row["id"] for row in body["addresses"]], [home, shore])
		self.assertEqual(set(body["addresses"][0]), set(StoreCustomerAddress.model_fields))
		self.assertEqual(body["addresses"][0]["customer_id"], self.reference.name)

	def test_list_honours_the_window_and_the_fields_selector(self):
		home = self._committed_entry(address_name="Home")
		shore = self._committed_entry(address_1="2 Shore Road", city="Salem")
		depot = self._committed_entry(address_1="3 Depot Street", city="Salem")

		with self.set_user(self.email):
			window = self._dispatch("GET", "/ceto/store/customers/me/addresses?limit=2&offset=1")
			projected = self._dispatch("GET", "/ceto/store/customers/me/addresses?fields=id,city")

		self.assertEqual(window.status_code, 200)
		self.assertEqual(window.get_json()["count"], 3)
		self.assertEqual(window.get_json()["offset"], 1)
		self.assertEqual(window.get_json()["limit"], 2)
		self.assertEqual([row["id"] for row in window.get_json()["addresses"]], [shore, depot])
		self.assertEqual(projected.status_code, 200)
		self.assertEqual(projected.get_json()["count"], 3)
		self.assertEqual(set(projected.get_json()["addresses"][0]), {"id", "city"})
		self.assertEqual(projected.get_json()["addresses"][0]["id"], home)

	def test_list_rejects_unknown_and_dropped_query_parameters(self):
		self._committed_entry()
		with self.set_user(self.email):
			for query in ("?company=Harbor", "?province=Oregon", "?limit=0", "?not_a_field=1"):
				with self.subTest(query=query):
					response = self._dispatch("GET", f"/ceto/store/customers/me/addresses{query}")
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")

	# ---------------------------------------------------------------- create

	def test_create_returns_the_parent_customer_with_the_new_entry(self):
		with self.set_user(self.email):
			response = self._dispatch(
				"POST",
				"/ceto/store/customers/me/addresses",
				self._payload(is_default_billing=True, metadata={"wing": "east"}, address_name="Home"),
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"customer"})
		customer = response.get_json()["customer"]
		self.assertEqual(set(customer), set(StoreCustomer.model_fields))
		self.assertEqual(len(customer["addresses"]), 1)
		entry = customer["addresses"][0]
		self.assertRegex(entry["id"], r"^addr_[0-9a-f]{32}$")
		self.assertEqual(entry["customer_id"], self.reference.name)
		self.assertEqual(entry["address_name"], "Home")
		self.assertEqual(entry["metadata"], {"wing": "east"})
		self.assertTrue(entry["is_default_billing"])
		self.assertFalse(entry["is_default_shipping"])
		self.assertEqual(customer["default_billing_address_id"], entry["id"])
		self.assertIsNone(customer["default_shipping_address_id"])

	def test_create_honours_the_fields_selector(self):
		with self.set_user(self.email):
			response = self._dispatch(
				"POST",
				"/ceto/store/customers/me/addresses?fields=id,addresses",
				self._payload(),
			)

		self.assertEqual(response.status_code, 200)
		customer = response.get_json()["customer"]
		self.assertEqual(set(customer), {"id", "addresses"})
		self.assertEqual(customer["id"], self.reference.name)
		self.assertEqual(len(customer["addresses"]), 1)

	def test_create_rejects_invalid_payloads_without_writing(self):
		before = frappe.db.count("Address")
		with self.set_user(self.email):
			for label, payload in (
				("unknown field", {**self._payload(), "email": "other@example.com"}),
				("missing core", {"address_1": "1 Harbor Way"}),
			):
				with self.subTest(payload=label):
					response = self._dispatch("POST", "/ceto/store/customers/me/addresses", payload)
					self.assertEqual(response.status_code, 400)
					self.assertEqual(response.get_json()["type"], "invalid_data")
		self.assertEqual(frappe.db.count("Address"), before)

	def test_an_invalid_fields_selector_rolls_the_create_back(self):
		with self.set_user(self.email):
			failed = self._dispatch(
				"POST",
				"/ceto/store/customers/me/addresses?fields=not_a_field",
				self._payload(),
			)
			self.assertEqual(failed.status_code, 400)
			self.assertEqual(failed.get_json()["type"], "invalid_data")
			# The selector projects after the create ran, so the 400 must
			# roll the created entry back with the whole request.
			listing = self._dispatch("GET", "/ceto/store/customers/me/addresses")

		self.assertEqual(listing.get_json()["count"], 0)

	# -------------------------------------------------------------- retrieve

	def test_retrieve_returns_the_projected_entry(self):
		name = self._committed_entry(address_name="Home", metadata={"wing": "east"})

		with self.set_user(self.email):
			full = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{name}")
			projected = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{name}?fields=id,city")
			rejected = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{name}?limit=5")

		self.assertEqual(full.status_code, 200)
		self.assertEqual(set(full.get_json()), {"address"})
		self.assertEqual(set(full.get_json()["address"]), set(StoreCustomerAddress.model_fields))
		self.assertEqual(full.get_json()["address"]["id"], name)
		self.assertEqual(full.get_json()["address"]["metadata"], {"wing": "east"})
		self.assertEqual(projected.status_code, 200)
		self.assertEqual(projected.get_json()["address"], {"id": name, "city": "Portland"})
		self.assertEqual(rejected.status_code, 400)
		self.assertEqual(rejected.get_json()["type"], "invalid_data")

	def test_retrieve_masks_missing_foreign_and_disabled_entries(self):
		foreign = self._committed_peer_entry()
		mine = self._committed_entry()
		frappe.db.set_value("Address", mine, "disabled", 1)
		frappe.db.commit()  # nosemgrep

		with self.set_user(self.email):
			for address_id in (_UNKNOWN_ADDRESS_ID, foreign, mine):
				with self.subTest(address_id=address_id):
					response = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{address_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(
						response.get_json(),
						{"type": "not_found", "message": "No customer address exists at this id"},
					)

	# ---------------------------------------------------------------- update

	def test_update_moves_only_the_supplied_fields_and_returns_the_parent(self):
		name = self._committed_entry(address_name="Home")
		before = frappe.db.get_value("Address", name, "modified")

		with self.set_user(self.email):
			response = self._dispatch(
				"POST",
				f"/ceto/store/customers/me/addresses/{name}",
				{"city": "Seattle", "is_default_shipping": True},
			)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(set(response.get_json()), {"customer"})
		customer = response.get_json()["customer"]
		self.assertEqual(set(customer), set(StoreCustomer.model_fields))
		self.assertEqual(customer["default_shipping_address_id"], name)
		self.assertIsNone(customer["default_billing_address_id"])
		row = frappe.db.get_value("Address", name, ["city", "address_line1", "address_title"], as_dict=True)
		self.assertEqual(row.city, "Seattle")
		self.assertEqual(row.address_line1, "1 Harbor Way")
		self.assertEqual(row.address_title, "Home")
		self.assertNotEqual(frappe.db.get_value("Address", name, "modified"), before)

	def test_an_invalid_fields_selector_rolls_the_update_back(self):
		name = self._committed_entry(city="Portland")

		with self.set_user(self.email):
			failed = self._dispatch(
				"POST",
				f"/ceto/store/customers/me/addresses/{name}?fields=not_a_field",
				{"city": "Seattle"},
			)
			self.assertEqual(failed.status_code, 400)
			self.assertEqual(failed.get_json()["type"], "invalid_data")
			after = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{name}?fields=city")

		self.assertEqual(after.get_json()["address"]["city"], "Portland")

	def test_update_rejects_unknown_fields_and_masks_foreign_entries(self):
		foreign = self._committed_peer_entry()
		mine = self._committed_entry()

		with self.set_user(self.email):
			unknown = self._dispatch(
				"POST", f"/ceto/store/customers/me/addresses/{mine}", {"postal": "97201"}
			)
			foreign_response = self._dispatch(
				"POST", f"/ceto/store/customers/me/addresses/{foreign}", {"city": "Salem"}
			)

		self.assertEqual(unknown.status_code, 400)
		self.assertEqual(unknown.get_json()["type"], "invalid_data")
		self.assertEqual(foreign_response.status_code, 404)
		self.assertEqual(foreign_response.get_json()["type"], "not_found")
		self.assertEqual(frappe.db.get_value("Address", foreign, "city"), "Salem")

	# ---------------------------------------------------------------- delete

	def test_delete_returns_the_pinned_shape_and_unlists_the_entry(self):
		name = self._committed_entry(is_default_billing=True)

		with self.set_user(self.email):
			response = self._dispatch("DELETE", f"/ceto/store/customers/me/addresses/{name}")

		self.assertEqual(response.status_code, 200)
		body = response.get_json()
		self.assertEqual(set(body), {"id", "object", "deleted", "parent"})
		self.assertEqual(body["id"], name)
		self.assertEqual(body["object"], "address")
		self.assertTrue(body["deleted"])
		parent = body["parent"]
		self.assertEqual(parent["id"], self.reference.name)
		self.assertEqual(parent["addresses"], [])
		self.assertIsNone(parent["default_billing_address_id"])
		self.assertFalse(frappe.db.exists("Address", name))
		self.assertFalse(frappe.db.exists("Ceto Customer Address Reference", name))

		with self.set_user(self.email):
			gone = self._dispatch("GET", f"/ceto/store/customers/me/addresses/{name}")
		self.assertEqual(gone.status_code, 404)

	def test_delete_masks_missing_and_foreign_entries(self):
		foreign = self._committed_peer_entry()

		with self.set_user(self.email):
			for address_id in (_UNKNOWN_ADDRESS_ID, foreign):
				with self.subTest(address_id=address_id):
					response = self._dispatch("DELETE", f"/ceto/store/customers/me/addresses/{address_id}")
					self.assertEqual(response.status_code, 404)
					self.assertEqual(response.get_json()["type"], "not_found")
		self.assertTrue(frappe.db.exists("Address", foreign))

	# ------------------------------------------------- profile serialization

	def test_profile_routes_carry_the_address_book(self):
		name = self._committed_entry(address_name="Home", is_default_billing=True, metadata={"wing": "east"})

		with self.set_user(self.email):
			response = self._dispatch("GET", "/ceto/store/customers/me")

		self.assertEqual(response.status_code, 200)
		customer = response.get_json()["customer"]
		self.assertEqual([entry["id"] for entry in customer["addresses"]], [name])
		self.assertEqual(customer["addresses"][0]["address_name"], "Home")
		self.assertEqual(customer["addresses"][0]["metadata"], {"wing": "east"})
		self.assertEqual(customer["default_billing_address_id"], name)
		self.assertIsNone(customer["default_shipping_address_id"])
