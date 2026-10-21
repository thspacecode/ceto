"""Pinned ``StoreLocale`` entity contract and the labeled Ceto list extension."""

import unittest

from pydantic import ValidationError

from ceto.types.http.store.locales import StoreLocale, StoreLocaleListResponse


class TestStoreLocaleEntity(unittest.TestCase):
	def test_constructs_with_the_pinned_columns_only(self):
		locale = StoreLocale(code="en-US", name="English (United States)")
		self.assertEqual(locale.code, "en-US")
		self.assertEqual(locale.name, "English (United States)")
		# The pinned entity carries nothing else — provisioning differences
		# live on the response, not the locale.
		self.assertEqual(set(StoreLocale.model_fields), {"code", "name"})

	def test_pinned_required_columns_cannot_be_omitted(self):
		with self.assertRaises(ValidationError):
			StoreLocale(code="en-US")
		with self.assertRaises(ValidationError):
			StoreLocale(name="English")


class TestStoreLocaleListResponseExtension(unittest.TestCase):
	def test_envelope_is_the_pinned_unpaged_shape(self):
		response = StoreLocaleListResponse(locales=[StoreLocale(code="en", name="English")])
		self.assertEqual(len(response.locales), 1)
		# Upstream {locales} is unpaged — no count/offset/limit columns.
		self.assertEqual(set(StoreLocaleListResponse.model_fields), {"locales", "default_locale"})

	def test_default_locale_is_the_labeled_ceto_extension(self):
		# Not part of @medusajs/types@2.21.1: optional, defaults to None, and
		# must never be fabricated for an empty locale set.
		response = StoreLocaleListResponse(locales=[])
		self.assertIsNone(response.default_locale)
		response = StoreLocaleListResponse(
			locales=[StoreLocale(code="en", name="English")], default_locale="en"
		)
		self.assertEqual(response.default_locale, "en")
