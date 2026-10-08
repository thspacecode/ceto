"""Serialization into the pinned ``StoreCustomer`` shape (Phase 0 contract).

Pins the column sources recorded in ``docs/customers/field-mapping.md``: the
public id and metadata from the reference, the profile columns from the
Contact, the identity email from the User, the timestamps from the Customer,
the always-serialized ``addresses`` relation from the customer's address book
(Ceto policy) and the default ids derived from the flagged book entries
(recorded decision 6).
"""

import json

import frappe

from ceto.services.customers.addresses import book_names, create_address
from ceto.services.customers.creation import create_customer_profile
from ceto.services.customers.serialization import CustomerSerializer
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, new_identity
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.customers import StoreCreateCustomerAddress, StoreCustomer


class TestCustomerSerializer(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			self.email = new_identity("serialize")
			self.identity, self.reference = create_customer_profile(
				self.email,
				first_name="Aria",
				last_name="Stone",
				company_name="Harbor Co.",
				phone="+1 555 0100",
				metadata={"loyalty_tier": "gold"},
			)

	def test_serializes_the_pinned_shape(self) -> None:
		customer = CustomerSerializer.serialize(self.identity, self.reference)

		self.assertIsInstance(customer, StoreCustomer)
		self.assertEqual(customer.id, self.reference.name)
		self.assertRegex(customer.id, r"^cus_[0-9a-f]{32}$")
		self.assertEqual(customer.email, self.email)
		self.assertEqual(customer.first_name, "Aria")
		self.assertEqual(customer.last_name, "Stone")
		self.assertEqual(customer.company_name, "Harbor Co.")
		self.assertEqual(customer.phone, "+1 555 0100")
		self.assertEqual(customer.metadata, {"loyalty_tier": "gold"})
		self.assertIsNone(customer.default_billing_address_id)
		self.assertIsNone(customer.default_shipping_address_id)
		self.assertEqual(customer.addresses, [])

	def test_serializes_the_customer_timestamps(self) -> None:
		created, modified = frappe.db.get_value("Customer", self.identity.customer, ["creation", "modified"])

		customer = CustomerSerializer.serialize(self.identity, self.reference)

		self.assertEqual(customer.created_at, created)
		self.assertEqual(customer.updated_at, modified)

	def test_omits_unset_columns(self) -> None:
		with self.set_conf(throttle_user_limit=THROTTLE_USER_LIMIT):
			email = new_identity("sparse")
			identity, reference = create_customer_profile(email)

		customer = CustomerSerializer.serialize(identity, reference)

		# The profile columns not in the create payload keep the reused
		# auto-Contact's registration fallback; nothing else is invented.
		self.assertEqual(customer.first_name, frappe.db.get_value("Contact", identity.contact, "first_name"))
		self.assertIsNone(customer.last_name)
		self.assertIsNone(customer.company_name)
		self.assertIsNone(customer.phone)
		self.assertIsNone(customer.metadata)
		self.assertIsNone(customer.default_billing_address_id)
		self.assertIsNone(customer.default_shipping_address_id)
		self.assertEqual(customer.addresses, [])
		self.assertEqual(customer.email, email)
		# The public id is always the reference; no ERPNext name leaks.
		self.assertNotIn(customer.id, [identity.customer, identity.contact])

	def test_metadata_roundtrips_storage_json(self) -> None:
		self.assertEqual(
			json.loads(self.reference.metadata),
			CustomerSerializer.serialize(self.identity, self.reference).metadata,
		)

	# ---------------------------------------------------------- address book

	def _entry(self, **overrides) -> str:
		"""Append one book entry through the address service; return its id."""
		values = {"address_1": "1 Harbor Way", "city": "Portland", "country_code": "us"}
		values.update(overrides)
		create_address(self.email, StoreCreateCustomerAddress(**values))
		return book_names(self.identity.customer)[-1]

	def test_serializes_the_address_book_into_the_relation(self) -> None:
		home = self._entry(address_name="Home", metadata={"wing": "east"}, address_2="Suite 3")
		shore = self._entry(address_1="2 Shore Road", city="Salem", is_default_shipping=True)

		customer = CustomerSerializer.serialize(self.identity, self.reference)

		# The whole enabled book, in the deterministic book order.
		self.assertEqual([entry.id for entry in customer.addresses], [home, shore])
		self.assertEqual(
			[entry.customer_id for entry in customer.addresses],
			[self.reference.name, self.reference.name],
		)
		home_entry, shore_entry = customer.addresses
		self.assertEqual(home_entry.address_name, "Home")
		self.assertEqual(home_entry.city, "Portland")
		self.assertEqual(home_entry.address_2, "Suite 3")
		self.assertEqual(home_entry.metadata, {"wing": "east"})
		self.assertFalse(home_entry.is_default_shipping)
		self.assertEqual(shore_entry.city, "Salem")
		self.assertTrue(shore_entry.is_default_shipping)
		self.assertFalse(shore_entry.is_default_billing)
		self.assertEqual(shore_entry.country_code, "us")

	def test_derives_the_default_ids_from_the_flagged_entries(self) -> None:
		billing = self._entry(is_default_billing=True)
		shipping = self._entry(is_default_shipping=True)

		customer = CustomerSerializer.serialize(self.identity, self.reference)

		self.assertEqual(customer.default_billing_address_id, billing)
		self.assertEqual(customer.default_shipping_address_id, shipping)
		self.assertEqual([entry.id for entry in customer.addresses], [billing, shipping])

	def test_a_moved_default_flag_moves_the_derived_id(self) -> None:
		first = self._entry(is_default_billing=True)
		second = self._entry(is_default_billing=True)

		customer = CustomerSerializer.serialize(self.identity, self.reference)

		# The controller cleared the previous per-customer holder, so the
		# derived id follows the flagged row.
		self.assertEqual(customer.default_billing_address_id, second)
		by_id = {entry.id: entry for entry in customer.addresses}
		self.assertFalse(by_id[first].is_default_billing)
		self.assertTrue(by_id[second].is_default_billing)

	def test_disabled_entries_leave_the_relation_and_the_default_ids(self) -> None:
		entry = self._entry(is_default_billing=True)
		frappe.db.set_value("Address", entry, "disabled", 1)

		customer = CustomerSerializer.serialize(self.identity, self.reference)

		self.assertEqual(customer.addresses, [])
		self.assertIsNone(customer.default_billing_address_id)
		self.assertIsNone(customer.default_shipping_address_id)

	def test_a_peer_book_never_leaks_into_the_relation(self) -> None:
		peer_identity, peer_reference = create_customer_profile(new_identity("serialize-peer"))
		self._entry()
		create_address(
			peer_identity.user,
			StoreCreateCustomerAddress(address_1="9 Elsewhere", city="Salem", country_code="us"),
		)

		mine = CustomerSerializer.serialize(self.identity, self.reference)
		theirs = CustomerSerializer.serialize(peer_identity, peer_reference)

		self.assertEqual(len(mine.addresses), 1)
		self.assertEqual(mine.addresses[0].customer_id, self.reference.name)
		self.assertEqual(len(theirs.addresses), 1)
		self.assertEqual(theirs.addresses[0].customer_id, peer_reference.name)
