import frappe

from ceto.services.payments.policy import POLICY_CONFIG_KEY, resolve_payment_policy
from ceto.tests.utils import CetoTestSuite


class TestPaymentPolicy(CetoTestSuite):
	def test_unset_policy_defaults_to_off(self):
		# Backward compatibility: a site that never configured payments must
		# keep the open gate it had before Phase 5.
		with self.set_conf():
			policy = resolve_payment_policy()
		self.assertEqual((policy.mode, policy.source), ("off", "default"))
		self.assertFalse(policy.enforced)

	def test_off_policy_is_off(self):
		with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: "off"}):
			policy = resolve_payment_policy()
		self.assertEqual((policy.mode, policy.source), ("off", "configured"))
		self.assertFalse(policy.enforced)

	def test_enforced_policy_is_enforced(self):
		with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: "enforced"}):
			policy = resolve_payment_policy()
		self.assertEqual((policy.mode, policy.source), ("enforced", "configured"))
		self.assertTrue(policy.enforced)

	def test_policy_is_case_and_whitespace_insensitive(self):
		for raw in ("Enforced", "  ENFORCED  ", "\tenforced\n"):
			with self.subTest(raw=raw):
				with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: raw}):
					self.assertTrue(resolve_payment_policy().enforced)
		for raw in (" Off ", "OFF"):
			with self.subTest(raw=raw):
				with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: raw}):
					self.assertFalse(resolve_payment_policy().enforced)

	def test_blank_policy_defaults_to_off(self):
		for raw in (None, "", "   "):
			with self.subTest(raw=raw):
				with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: raw}):
					policy = resolve_payment_policy()
			self.assertEqual((policy.mode, policy.source), ("off", "default"))

	def test_unknown_policy_fails_closed_as_enforced(self):
		# An operator typo may only make checkout stricter, never looser.
		for raw in ("required", "on", "of", "enforce", 1, True):
			with self.subTest(raw=raw):
				with self.set_conf(ceto_cart={POLICY_CONFIG_KEY: raw}):
					policy = resolve_payment_policy()
				self.assertEqual((policy.mode, policy.source), ("enforced", "fallback"))
				self.assertTrue(policy.enforced)

	def test_non_mapping_ceto_cart_section_fails_closed(self):
		for broken in ("enforced", ["off"], 42):
			with self.subTest(broken=broken):
				with self.set_conf(ceto_cart=broken):
					policy = resolve_payment_policy()
				self.assertEqual((policy.mode, policy.source), ("enforced", "fallback"))

	def test_policy_reads_only_the_ceto_cart_section(self):
		# The policy lives beside the other cart settings, not at the config
		# root: a same-named root key must not be picked up.
		with self.set_conf(payment_policy="enforced", ceto_cart={POLICY_CONFIG_KEY: "off"}):
			self.assertFalse(resolve_payment_policy().enforced)
