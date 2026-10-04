"""Pinned customer query parameter contracts.

Pins the fields selector, the pagination window of the address list, the
pinned address filters (with ``company``/``province`` dropped by the pinned
``Omit``) and the unknown-parameter strictness of
``@medusajs/types@2.21.1`` (``http/customer/store``).
"""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.customers import (
	StoreCustomerAddressFilters,
	StoreGetCustomerAddressParams,
	StoreGetCustomerParams,
)


class TestStoreGetCustomerParams(unittest.TestCase):
	def test_accepts_a_fields_selector(self):
		params = StoreGetCustomerParams(fields="id,email,addresses")
		self.assertEqual(params.fields, "id,email,addresses")

	def test_accepts_an_empty_query(self):
		self.assertEqual(StoreGetCustomerParams().model_dump(), {"fields": None})

	def test_rejects_pagination_and_filters(self):
		with self.assertRaises(ValidationError):
			StoreGetCustomerParams(limit=10)
		with self.assertRaises(ValidationError):
			StoreGetCustomerParams(q="nara")

	def test_rejects_unknown_parameters(self):
		with self.assertRaises(ValidationError):
			StoreGetCustomerAddressParams(email="customer@example.com")


class TestStoreCustomerAddressFilters(unittest.TestCase):
	def test_accepts_the_pinned_filter_columns(self):
		params = StoreCustomerAddressFilters(
			q="sukhumvit", city="Bangkok", country_code="TH", postal_code="10110"
		)
		self.assertEqual(params.country_code, "th")
		self.assertEqual(params.city, "Bangkok")

	def test_country_code_filter_rejects_non_letter_two_letter_values(self):
		# ISO 3166-1 alpha-2 means ASCII letters, so digits, punctuation and
		# non-ASCII letters fail even at the two-character length. The escapes
		# are a Greek (U+03A4 U+0397) and a fullwidth (U+FF35 U+FF33) pair.
		for bad in ("12", "U;", "\u03a4\u0397", "\uff35\uff33"):
			with self.subTest(country_code=bad):
				with self.assertRaises(ValidationError):
					StoreCustomerAddressFilters(country_code=bad)

	def test_accepts_the_pagination_window(self):
		params = StoreCustomerAddressFilters(limit=10, offset=5, order="-created_at")
		self.assertEqual((params.limit, params.offset, params.order), (10, 5, "-created_at"))

	def test_rejects_an_unbounded_or_empty_window(self):
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(limit=0)
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(limit=101)
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(offset=-1)

	def test_company_and_province_are_omitted_by_the_pinned_type(self):
		# The pinned StoreCustomerAddressFilters is
		# Omit<BaseCustomerAddressFilters, "company" | "province">.
		self.assertNotIn("company", StoreCustomerAddressFilters.model_fields)
		self.assertNotIn("province", StoreCustomerAddressFilters.model_fields)
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(company="Space Code")
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(province="th-10")

	def test_rejects_unknown_parameters(self):
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(is_default_shipping="true")

	def test_rejects_array_filter_values(self):
		# Ceto implements the single-value member of the pinned
		# string | string[] unions only.
		with self.assertRaises(ValidationError):
			StoreCustomerAddressFilters(city=["Bangkok", "Chiang Mai"])


if __name__ == "__main__":
	unittest.main()
