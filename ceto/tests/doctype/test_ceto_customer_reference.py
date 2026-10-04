"""Phase 1 identity record: Ceto Customer Reference persistence.

Runs against real Frappe behaviour on the test site inside a single
rolled-back transaction: the reference names the public ``cus_…`` id, maps it
one-to-one onto the ERPNext Customer and its owning registration User, and
only blesses an identity chain the resolver would accept.
"""

import json
import uuid

import frappe

from ceto.tests.data.customer_test_data import make_chain, make_customer, new_identity
from ceto.tests.utils import CetoTestSuite


class TestCetoCustomerReference(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		with self.set_conf(throttle_user_limit=100000):
			self.email, self.customer, self.contact = make_chain("ref")

	def _make_reference(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Customer Reference",
				"customer_id": f"cus_{uuid.uuid4().hex}",
				"customer": self.customer,
				"user": self.email,
				"metadata": '{"source": "test"}',
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_reference_by_public_customer_id(self) -> None:
		reference = self._make_reference()

		loaded = frappe.get_doc("Ceto Customer Reference", reference.name)
		self.assertEqual(loaded.name, reference.customer_id)
		self.assertRegex(loaded.name, r"^cus_[0-9a-f]{32}$")
		self.assertEqual(loaded.customer, self.customer)
		self.assertEqual(loaded.user, self.email)

	def test_public_customer_id_is_unique(self) -> None:
		customer_id = f"cus_{uuid.uuid4().hex}"
		self._make_reference(customer_id=customer_id)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_reference(customer_id=customer_id)

	def test_one_reference_per_customer(self) -> None:
		self._make_reference()
		# A pre-existing Customer already owned by a Ceto reference must
		# never gain a second public identity.
		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self._make_reference(customer_id=f"cus_{uuid.uuid4().hex}")

	def test_one_reference_per_user(self) -> None:
		self._make_reference()
		# The chain moves to a second Customer so the identity-chain check
		# passes and the unique User index alone refuses the second
		# reference — one Customer per user, at the schema level.
		other = make_customer("ref-user")
		contact = frappe.get_doc("Contact", self.contact)
		contact.links = []
		contact.append("links", {"link_doctype": "Customer", "link_name": other})
		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True)

		with self.assertRaises(frappe.exceptions.UniqueValidationError):
			self._make_reference(customer=other)

	def test_rejects_malformed_public_customer_id(self) -> None:
		for customer_id in (
			"cust_123",
			f"cus_{uuid.uuid4().hex[:31]}",
			f"cus_{uuid.uuid4().hex}0",
			f"cus_{uuid.uuid4().hex.upper()}",
			f"customer_{uuid.uuid4().hex}",
			uuid.uuid4().hex,
		):
			with self.subTest(customer_id=customer_id):
				with self.assertRaises(frappe.exceptions.ValidationError):
					self._make_reference(customer_id=customer_id)

	def test_rejects_unknown_customer(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(customer=f"missing-{uuid.uuid4().hex}")

	def test_rejects_unknown_user(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(user=f"ghost-{uuid.uuid4().hex}@example.com")

	def test_rejects_customer_outside_the_identity_chain(self) -> None:
		# The chain links one Customer; a reference naming any other Customer
		# would bless an identity the resolver refuses.
		other = make_customer("ref-foreign")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(customer=other)

	def test_rejects_ambiguous_identity_chain(self) -> None:
		other = make_customer("ref-ambiguous")
		contact = frappe.get_doc("Contact", self.contact)
		contact.append("links", {"link_doctype": "Customer", "link_name": other})
		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True)

		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference()

	def test_rejects_user_without_a_linked_customer(self) -> None:
		with self.set_conf(throttle_user_limit=100000):
			unlinked = new_identity("ref-unlinked")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(user=unlinked)

	def test_rejects_non_object_metadata(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(metadata="[1, 2]")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(metadata="not json")

	def test_accepts_missing_metadata(self) -> None:
		reference = self._make_reference(metadata=None)

		loaded = frappe.get_doc("Ceto Customer Reference", reference.name)
		self.assertIsNone(loaded.metadata)

	def test_roundtrips_object_metadata(self) -> None:
		metadata = {"loyalty_tier": "gold", "source": "test"}
		reference = self._make_reference(metadata=json.dumps(metadata))

		loaded = frappe.get_doc("Ceto Customer Reference", reference.name)
		self.assertEqual(json.loads(loaded.metadata), metadata)
