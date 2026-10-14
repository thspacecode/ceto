"""Focused tests for the reversible ``so_`` option-id codec."""

import unittest

from ceto.services.shipping.errors import MalformedShippingOptionIdError, ShippingOptionError
from ceto.services.shipping.ids import decode_option_id, encode_option_id

PINNED_PROVIDER = "erpnext"
PINNED_OPTION_KEY = "Dev Flat Rate"
#: The vector the pinned entity contract serves as the built-in provider's
#: opaque id for the ``Dev Flat Rate`` rule.
PINNED_OPTION_ID = "so_ZXJwbmV4dDpEZXYgRmxhdCBSYXRl"


class TestOptionIdEncoding(unittest.TestCase):
	def test_encodes_the_pinned_contract_vector(self) -> None:
		self.assertEqual(encode_option_id(PINNED_PROVIDER, PINNED_OPTION_KEY), PINNED_OPTION_ID)

	def test_tokens_stay_url_safe_and_unpadded(self) -> None:
		for key in ("a", "ab", "abc", "abcd", "rate with spaces & ?=/plus", "x" * 200):
			with self.subTest(option_key=key):
				self.assertRegex(encode_option_id("p", key), r"^so_[A-Za-z0-9_-]+$")

	def test_refuses_blank_identity_parts(self) -> None:
		for provider, key in (("", "key"), ("   ", "key"), ("p", ""), ("p", "   ")):
			with self.subTest(provider=provider, option_key=key):
				with self.assertRaises(ShippingOptionError):
					encode_option_id(provider, key)

	def test_refuses_a_separator_bearing_provider_id(self) -> None:
		# The provider id cannot contain the separator: the split on decode
		# takes the first colon, so such an id could never round-trip.
		with self.assertRaises(ShippingOptionError):
			encode_option_id("a:b", "key")


class TestOptionIdDecoding(unittest.TestCase):
	def test_decodes_the_pinned_vector(self) -> None:
		self.assertEqual(decode_option_id(PINNED_OPTION_ID), (PINNED_PROVIDER, PINNED_OPTION_KEY))

	def test_round_trips_identities(self) -> None:
		for provider, key in (
			("erpnext", "Dev Flat Rate"),
			("prov-with-dashes_and_underscores", 'key/with stuff?="&'),
			("p", "multi:part:key"),
			("ünïcode", "össz"),
		):
			with self.subTest(provider=provider, option_key=key):
				self.assertEqual(decode_option_id(encode_option_id(provider, key)), (provider, key))

	def test_refuses_malformed_ids(self) -> None:
		for option_id in (
			None,
			12,
			"",
			"Dev Flat Rate",
			"prod_abc",
			"SO_A",
			"so_",
			"so_YQ",  # decodes to "i": no separator
			"so_Oms",  # decodes to ":k": blank provider
			"so_YTo",  # decodes to "a:": blank key
			"so_ab=",  # padding is not part of the token shape
			"so_+/?",  # foreign base64 characters
			"so___",  # bytes that are not UTF-8 text
			"so.abc",
		):
			with self.subTest(option_id=option_id):
				with self.assertRaises(MalformedShippingOptionIdError):
					decode_option_id(option_id)


if __name__ == "__main__":
	unittest.main()
