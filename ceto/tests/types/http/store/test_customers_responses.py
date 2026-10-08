"""Pinned customer response body contracts.

Pins the wrapper shapes, the pagination envelope and the exact address
deletion shape of ``@medusajs/types@2.21.1`` (``http/customer/store``).
"""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.customers import (
	StoreCustomer,
	StoreCustomerAddress,
	StoreCustomerAddressDeleteResponse,
	StoreCustomerAddressListResponse,
	StoreCustomerAddressResponse,
	StoreCustomerResponse,
)

TIMESTAMP = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def customer(**overrides):
	kwargs = {"id": "cus_123", "email": "customer@example.com"}
	kwargs.update(overrides)
	return StoreCustomer(**kwargs)


def address(**overrides):
	kwargs = {
		"id": "CUST-Addr-0001",
		"customer_id": "cus_123",
		"is_default_shipping": True,
		"is_default_billing": False,
		"created_at": TIMESTAMP,
		"updated_at": TIMESTAMP,
	}
	kwargs.update(overrides)
	return StoreCustomerAddress(**kwargs)


class TestWrappers(unittest.TestCase):
	def test_customer_response_wraps_the_customer(self):
		response = StoreCustomerResponse(customer=customer())
		self.assertEqual(response.customer.email, "customer@example.com")
		with self.assertRaises(ValidationError):
			StoreCustomerResponse()

	def test_address_response_wraps_the_address(self):
		response = StoreCustomerAddressResponse(address=address())
		self.assertEqual(response.address.id, "CUST-Addr-0001")
		with self.assertRaises(ValidationError):
			StoreCustomerAddressResponse(address={"id": "CUST-Addr-0001"})


class TestStoreCustomerAddressListResponse(unittest.TestCase):
	def test_requires_the_pagination_envelope(self):
		response = StoreCustomerAddressListResponse(addresses=[address()], count=1, offset=0, limit=20)
		self.assertEqual(response.count, 1)
		self.assertEqual(response.limit, 20)
		self.assertEqual(len(response.addresses), 1)

	def test_pagination_columns_cannot_be_omitted(self):
		for field in ("addresses", "count", "offset", "limit"):
			kwargs = {"addresses": [], "count": 0, "offset": 0, "limit": 20}
			kwargs.pop(field)
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreCustomerAddressListResponse(**kwargs)

	def test_estimate_count_is_deliberately_omitted(self):
		# The pinned PaginatedResponse carries an optional planner estimate
		# behind the index_engine feature flag; Ceto never reports one.
		self.assertNotIn("estimate_count", StoreCustomerAddressListResponse.model_fields)
		response = StoreCustomerAddressListResponse(addresses=[], count=0, offset=0, limit=20)
		self.assertNotIn("estimate_count", response.model_dump())


class TestStoreCustomerAddressDeleteResponse(unittest.TestCase):
	def test_pins_the_exact_deletion_shape(self):
		response = StoreCustomerAddressDeleteResponse(id="CUST-Addr-0001", parent=customer())
		self.assertEqual(response.object, "address")
		self.assertTrue(response.deleted)
		self.assertEqual(response.parent.id, "cus_123")

	def test_serializes_to_the_json_ready_envelope(self):
		parent = customer()
		dumped = StoreCustomerAddressDeleteResponse(id="CUST-Addr-0001", parent=parent).model_dump(
			mode="json"
		)
		self.assertEqual(dumped["id"], "CUST-Addr-0001")
		self.assertEqual(dumped["object"], "address")
		self.assertIs(dumped["deleted"], True)
		self.assertEqual(dumped["parent"], parent.model_dump(mode="json"))

	def test_rejects_extra_and_missing_fields(self):
		with self.assertRaises(ValidationError):
			StoreCustomerAddressDeleteResponse(id="a", parent=customer(), count=1)
		with self.assertRaises(ValidationError):
			StoreCustomerAddressDeleteResponse(id="a")

	def test_parent_is_the_full_customer(self):
		# The pinned DeleteResponseWithParent<"address", StoreCustomer> (the
		# SDK destructures { deleted, parent: customer }) — not an id like the
		# carts line-item delete.
		with self.assertRaises(ValidationError):
			StoreCustomerAddressDeleteResponse(id="CUST-Addr-0001", parent="cus_123")


if __name__ == "__main__":
	unittest.main()
