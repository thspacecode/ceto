"""Pinned ``StoreCustomer`` / ``StoreCustomerAddress`` entity contracts.

Mirrors ``http/customer/store`` of ``@medusajs/types@2.21.1``: required
columns, nullable defaults, the embedded address book and the deliberate
omissions (``created_by`` dropped by the pinned type itself, ``deleted_at``
dropped by Ceto policy).
"""

import unittest
from datetime import UTC, datetime

from pydantic import ValidationError

from ceto.types.http.store.customers import StoreCustomer, StoreCustomerAddress

TIMESTAMP = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def address(**overrides):
	kwargs = {
		"id": "CUST-Addr-0001",
		"customer_id": "cus_123",
		"is_default_shipping": False,
		"is_default_billing": False,
		"created_at": TIMESTAMP,
		"updated_at": TIMESTAMP,
	}
	kwargs.update(overrides)
	return StoreCustomerAddress(**kwargs)


class TestStoreCustomerAddressEntity(unittest.TestCase):
	def test_constructs_with_pinned_required_columns_only(self):
		entry = address()
		self.assertEqual(entry.customer_id, "cus_123")
		self.assertFalse(entry.is_default_shipping)
		self.assertFalse(entry.is_default_billing)
		self.assertIsNone(entry.address_name)
		self.assertIsNone(entry.country_code)

	def test_pinned_required_columns_cannot_be_omitted(self):
		# @medusajs/types@2.21.1 pins these as non-nullable columns.
		required = (
			"id",
			"customer_id",
			"is_default_shipping",
			"is_default_billing",
			"created_at",
			"updated_at",
		)
		for field in required:
			kwargs = {
				"id": "CUST-Addr-0001",
				"customer_id": "cus_123",
				"is_default_shipping": False,
				"is_default_billing": True,
				"created_at": TIMESTAMP,
				"updated_at": TIMESTAMP,
			}
			kwargs.pop(field)
			with self.subTest(field=field), self.assertRaises(ValidationError):
				StoreCustomerAddress(**kwargs)

	def test_default_flags_accept_only_booleans(self):
		with self.assertRaises(ValidationError):
			address(is_default_shipping="maybe")
		self.assertTrue(address(is_default_billing=True).is_default_billing)

	def test_nullable_columns_default_to_unset(self):
		entry = address()
		for field in (
			"address_name",
			"company",
			"first_name",
			"last_name",
			"phone",
			"address_1",
			"address_2",
			"city",
			"province",
			"postal_code",
			"country_code",
			"metadata",
		):
			with self.subTest(field=field):
				self.assertIsNone(getattr(entry, field))

	def test_serializes_to_json_ready_values(self):
		dumped = address(city="Bangkok", country_code="th").model_dump(mode="json")
		self.assertEqual(dumped["created_at"], "2026-10-04T12:00:00Z")
		self.assertEqual(dumped["country_code"], "th")


class TestStoreCustomerEntity(unittest.TestCase):
	def test_constructs_with_identity_and_email_only(self):
		customer = StoreCustomer(id="cus_123", email="customer@example.com")
		self.assertEqual(customer.email, "customer@example.com")
		self.assertIsNone(customer.first_name)
		self.assertIsNone(customer.company_name)
		self.assertEqual(customer.addresses, [])

	def test_requires_identity_and_email(self):
		with self.assertRaises(ValidationError):
			StoreCustomer(email="customer@example.com")
		with self.assertRaises(ValidationError):
			StoreCustomer(id="cus_123")

	def test_email_stays_a_plain_public_string(self):
		# The pinned entity column is a plain string; stricter email syntax
		# belongs to the request payloads, not the response entity.
		customer = StoreCustomer(id="cus_123", email="not-an-email")
		self.assertEqual(customer.email, "not-an-email")

	def test_default_address_ids_and_carried_columns(self):
		customer = StoreCustomer(
			id="cus_123",
			email="customer@example.com",
			default_billing_address_id="CUST-Addr-0001",
			default_shipping_address_id="CUST-Addr-0002",
			company_name="Space Code Co., Ltd.",
			first_name="Nara",
			last_name="Thanapat",
			phone="+66810000000",
			metadata={"source": "storefront"},
		)
		self.assertEqual(customer.default_billing_address_id, "CUST-Addr-0001")
		self.assertEqual(customer.default_shipping_address_id, "CUST-Addr-0002")
		self.assertEqual(customer.metadata, {"source": "storefront"})

	def test_carries_the_address_book(self):
		customer = StoreCustomer(id="cus_123", email="customer@example.com", addresses=[address()])
		self.assertEqual(len(customer.addresses), 1)
		self.assertEqual(customer.addresses[0].customer_id, "cus_123")

	def test_created_by_is_omitted_by_the_pinned_type(self):
		# The pinned StoreCustomer is Omit<BaseCustomer, "created_by">.
		self.assertNotIn("created_by", StoreCustomer.model_fields)
		self.assertNotIn("created_by", StoreCustomer(id="cus_123", email="e@x.com").model_dump())

	def test_deleted_at_is_omitted_by_ceto_policy(self):
		# The pinned BaseCustomer carries an optional deleted_at; Ceto exposes
		# no soft-deleted customer surface (recorded decision).
		self.assertNotIn("deleted_at", StoreCustomer.model_fields)
		self.assertNotIn("deleted_at", StoreCustomer(id="cus_123", email="e@x.com").model_dump())

	def test_timestamps_default_to_unset(self):
		customer = StoreCustomer(id="cus_123", email="customer@example.com")
		self.assertIsNone(customer.created_at)
		self.assertIsNone(customer.updated_at)


if __name__ == "__main__":
	unittest.main()
