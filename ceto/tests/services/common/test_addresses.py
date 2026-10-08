"""Pins the shared Address helpers and the moved-helper compatibility imports.

ERPNext ``Address`` records back more than one Medusa surface, so the ISO
country resolution, the ``Address`` ↔ ``Customer`` ownership check and the
serialization into the pinned address entity live in
:cmod:`ceto.services.addresses` and run against real records inside one
rolled-back transaction.
"""

import uuid

import frappe

from ceto.routing.exceptions import InvalidDataError
from ceto.services.addresses import is_customer_address, resolve_country, serialize_address
from ceto.services.carts.addresses import (
	is_customer_address as cart_is_customer_address,
)
from ceto.services.carts.addresses import (
	resolve_country as cart_resolve_country,
)
from ceto.tests.data.customer_test_data import make_customer
from ceto.tests.utils import CetoTestSuite


class TestSharedAddresses(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def _make_address(self, customer: str | None = None):
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Shared Addr {uuid.uuid4().hex[:8]}",
				"address_type": "Billing",
				"address_line1": "1 Harbor Way",
				"address_line2": "Suite 3",
				"city": "Portland",
				"state": "Oregon",
				"pincode": "97201",
				"country": "United States",
				"phone": "+1 555 0100",
				"links": [{"link_doctype": "Customer", "link_name": customer}] if customer else [],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc

	def test_resolves_iso_country_codes_case_insensitively(self) -> None:
		self.assertEqual(resolve_country("us"), "United States")
		self.assertEqual(resolve_country("US"), "United States")
		self.assertEqual(resolve_country(" us "), "United States")

	def test_rejects_unknown_country_codes(self) -> None:
		with self.assertRaises(InvalidDataError):
			resolve_country("zz")

	def test_customer_address_ownership_follows_the_dynamic_link(self) -> None:
		customer = make_customer("shared-addr")
		address = self._make_address(customer)

		self.assertTrue(is_customer_address(address.name, customer))
		self.assertFalse(is_customer_address(address.name, make_customer("shared-addr-other")))
		self.assertFalse(is_customer_address(address.name, None))
		self.assertFalse(is_customer_address(f"missing-{uuid.uuid4().hex[:8]}", customer))

	def test_serializes_none_and_missing_addresses_to_none(self) -> None:
		self.assertIsNone(serialize_address(None))
		self.assertIsNone(serialize_address(f"missing-{uuid.uuid4().hex[:8]}"))

	def test_serializes_a_customer_linked_address(self) -> None:
		customer = make_customer("shared-serialize")
		address = self._make_address(customer)

		serialized = serialize_address(address.name)
		self.assertEqual(serialized.id, address.name)
		self.assertEqual(serialized.customer_id, customer)
		self.assertEqual(serialized.address_1, "1 Harbor Way")
		self.assertEqual(serialized.address_2, "Suite 3")
		self.assertEqual(serialized.city, "Portland")
		self.assertEqual(serialized.province, "Oregon")
		self.assertEqual(serialized.postal_code, "97201")
		self.assertEqual(serialized.country_code, "us")
		self.assertEqual(serialized.phone, "+1 555 0100")
		# The cart-scoped title collapse: names are never serialized back.
		self.assertIsNone(serialized.first_name)
		self.assertIsNone(serialized.last_name)
		self.assertIsNone(serialized.company)

	def test_cart_module_still_exposes_the_moved_helpers(self) -> None:
		# Compatibility imports: the cart addresses module keeps exposing the
		# helpers it uses, so downstream imports of the old path keep resolving.
		self.assertIs(cart_resolve_country, resolve_country)
		self.assertIs(cart_is_customer_address, is_customer_address)
