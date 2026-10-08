"""Phase 3 address-book record: Ceto Customer Address Reference persistence.

Runs against real Frappe behaviour on the test site inside a single
rolled-back transaction: the reference is named by the ERPNext Address (the
public address id, recorded decision 5 of ``docs/customers/field-mapping.md``),
carries the address's Medusa ``metadata`` object (decision 4), and only
blesses an address the owning customer links through its Dynamic Links.
"""

import json
import uuid

import frappe

from ceto.tests.data.customer_test_data import make_customer
from ceto.tests.utils import CetoTestSuite


class TestCetoCustomerAddressReference(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.customer = make_customer("addr-ref")

	def _make_address(self, customer: str | None, *, second_link: str | None = None):
		links = []
		if customer:
			links.append({"link_doctype": "Customer", "link_name": customer})
		if second_link:
			links.append({"link_doctype": "Customer", "link_name": second_link})
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Addr Ref {uuid.uuid4().hex[:8]}",
				"address_type": "Billing",
				"address_line1": "1 Harbor Way",
				"city": "Portland",
				"country": "United States",
				"links": links,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc

	def _make_reference(self, **overrides):
		doc = frappe.get_doc(
			{
				"doctype": "Ceto Customer Address Reference",
				"address": overrides.pop("address", None) or self._make_address(self.customer).name,
				"customer": overrides.pop("customer", None) or self.customer,
				"metadata": '{"source": "test"}',
				**overrides,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_names_reference_by_the_address(self) -> None:
		address = self._make_address(self.customer)
		reference = self._make_reference(address=address.name)

		loaded = frappe.get_doc("Ceto Customer Address Reference", reference.name)
		self.assertEqual(loaded.name, address.name)
		self.assertEqual(loaded.address, address.name)
		self.assertEqual(loaded.customer, self.customer)

	def test_one_reference_per_address(self) -> None:
		address = self._make_address(self.customer)
		self._make_reference(address=address.name)
		# The public address id names the record, so a second reference for
		# the same address would be a second identity for one address.
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			self._make_reference(address=address.name)

	def test_rejects_unknown_address(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(address=f"missing-{uuid.uuid4().hex}")

	def test_rejects_unknown_customer(self) -> None:
		address = self._make_address(self.customer)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(address=address.name, customer=f"missing-{uuid.uuid4().hex}")

	def test_rejects_address_linked_to_another_customer(self) -> None:
		# The address book is customer-owned: a reference naming any other
		# customer would bless an address outside the customer's book.
		address = self._make_address(self.customer)
		other = make_customer("addr-ref-foreign")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(address=address.name, customer=other)

	def test_rejects_address_without_a_customer_link(self) -> None:
		# Quotation-scoped addresses (cart temporaries) carry no Customer
		# link; they never belong to an address book.
		address = self._make_address(None)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(address=address.name)

	def test_rejects_ambiguous_customer_links(self) -> None:
		other = make_customer("addr-ref-ambiguous")
		address = self._make_address(self.customer, second_link=other)
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(address=address.name)

	def test_rejects_non_object_metadata(self) -> None:
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(metadata="[1, 2]")
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._make_reference(metadata="not json")

	def test_accepts_missing_metadata(self) -> None:
		reference = self._make_reference(metadata=None)

		loaded = frappe.get_doc("Ceto Customer Address Reference", reference.name)
		self.assertIsNone(loaded.metadata)

	def test_roundtrips_object_metadata(self) -> None:
		metadata = {"label": "home", "source": "test"}
		reference = self._make_reference(metadata=json.dumps(metadata))

		loaded = frappe.get_doc("Ceto Customer Address Reference", reference.name)
		self.assertEqual(json.loads(loaded.metadata), metadata)
