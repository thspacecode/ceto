"""Pinned customer request payload contracts.

Pins the unknown-field strictness of every body, the pinned ``Omit`` of
``email`` on ``StoreUpdateCustomer`` and the shared address-book payload shape
of ``@medusajs/types@2.21.1`` (``http/customer/store``).
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.customers import (
	StoreCreateCustomer,
	StoreCreateCustomerAddress,
	StoreUpdateCustomer,
	StoreUpdateCustomerAddress,
)


class TestStoreCreateCustomerPayload(unittest.TestCase):
	def test_accepts_an_empty_body(self):
		payload = StoreCreateCustomer()
		self.assertEqual(payload.model_dump(), {field: None for field in StoreCreateCustomer.model_fields})

	def test_accepts_the_profile_columns(self):
		payload = StoreCreateCustomer(
			email=" Customer@Example.com ",
			company_name="Space Code Co., Ltd.",
			first_name="Nara",
			last_name="Thanapat",
			phone="+66810000000",
			metadata={"source": "storefront"},
		)
		self.assertEqual(str(payload.email), "Customer@example.com")
		self.assertEqual(payload.first_name, "Nara")

	def test_strips_whitespace_but_not_metadata_values(self):
		payload = StoreCreateCustomer(first_name="  Nara  ", metadata={"note": "  keep  "})
		self.assertEqual(payload.first_name, "Nara")
		self.assertEqual(payload.metadata, {"note": "  keep  "})

	def test_rejects_an_invalid_email(self):
		with self.assertRaises(ValidationError):
			StoreCreateCustomer(email="not-an-email")

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreCreateCustomer(password="supersecret")


class TestStoreUpdateCustomerPayload(unittest.TestCase):
	def test_accepts_the_profile_columns(self):
		payload = StoreUpdateCustomer(first_name="Nara", metadata={"note": "vip"})
		self.assertEqual(payload.first_name, "Nara")
		self.assertEqual(payload.metadata, {"note": "vip"})

	def test_email_is_omitted_by_the_pinned_type(self):
		# The pinned StoreUpdateCustomer is Omit<BaseUpdateCustomer, "email">:
		# the login identity cannot be changed through this route.
		self.assertNotIn("email", StoreUpdateCustomer.model_fields)

	def test_rejects_an_email_key(self):
		with self.assertRaises(ValidationError):
			StoreUpdateCustomer(email="new@example.com")

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreUpdateCustomer(default_billing_address_id="CUST-Addr-0001")


class TestCustomerAddressPayloads(unittest.TestCase):
	def test_create_accepts_the_full_pinned_shape(self):
		payload = StoreCreateCustomerAddress(
			first_name="Nara",
			last_name="Thanapat",
			company="Space Code Co., Ltd.",
			phone="+66810000000",
			address_1="1 Sukhumvit Rd",
			address_2="Floor 2",
			city="Bangkok",
			province="th-10",
			postal_code="10110",
			country_code=" TH ",
			address_name="Office",
			is_default_shipping=True,
			is_default_billing=True,
			metadata={"label": "hq"},
		)
		self.assertEqual(payload.country_code, "th")
		self.assertTrue(payload.is_default_shipping)
		self.assertEqual(payload.address_name, "Office")

	def test_update_accepts_the_same_shape(self):
		payload = StoreUpdateCustomerAddress(city="Chiang Mai", is_default_billing=False)
		self.assertEqual(payload.city, "Chiang Mai")
		self.assertFalse(payload.is_default_billing)

	def test_every_field_is_optional(self):
		self.assertEqual(
			StoreCreateCustomerAddress().model_dump(),
			{field: None for field in StoreCreateCustomerAddress.model_fields},
		)
		self.assertEqual(
			StoreUpdateCustomerAddress().model_dump(),
			{field: None for field in StoreUpdateCustomerAddress.model_fields},
		)

	def test_country_code_is_normalized_and_validated(self):
		self.assertEqual(StoreCreateCustomerAddress(country_code="US").country_code, "us")
		with self.assertRaises(ValidationError):
			StoreCreateCustomerAddress(country_code="THA")
		with self.assertRaises(ValidationError):
			StoreUpdateCustomerAddress(country_code="")

	def test_rejects_extra_fields(self):
		with self.assertRaises(ValidationError):
			StoreCreateCustomerAddress(customer_id="cus_123")
		with self.assertRaises(ValidationError):
			StoreUpdateCustomerAddress(id="CUST-Addr-0001")

	def test_create_and_update_share_the_pinned_columns(self):
		self.assertEqual(
			set(StoreCreateCustomerAddress.model_fields), set(StoreUpdateCustomerAddress.model_fields)
		)


if __name__ == "__main__":
	unittest.main()
