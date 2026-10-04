"""Serialization into the pinned ``StoreCustomer`` shape (Phase 0 contract).

Pins the column sources recorded in ``docs/customers/field-mapping.md``: the
public id and metadata from the reference, the profile columns from the
Contact, the identity email from the User, the timestamps from the Customer,
and the always-serialized (phase-empty) ``addresses`` relation.
"""

import json

import frappe

from ceto.services.customers.creation import create_customer_profile
from ceto.services.customers.serialization import CustomerSerializer
from ceto.tests.data.customer_test_data import THROTTLE_USER_LIMIT, new_identity
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.customers import StoreCustomer


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
		self.assertEqual(customer.addresses, [])
		self.assertEqual(customer.email, email)
		# The public id is always the reference; no ERPNext name leaks.
		self.assertNotIn(customer.id, [identity.customer, identity.contact])

	def test_metadata_roundtrips_storage_json(self) -> None:
		self.assertEqual(
			json.loads(self.reference.metadata),
			CustomerSerializer.serialize(self.identity, self.reference).metadata,
		)
