from unittest.mock import patch

from ceto.services.payments.providers import (
	PaygiProvider,
	ProviderRegistry,
	default_registry,
	paygi_settings_enabled,
)
from ceto.tests.utils import CetoTestSuite


class EnabledProvider:
	def __init__(self, provider_id: str, enabled: bool = True) -> None:
		self.provider_id = provider_id
		self.enabled = enabled

	@property
	def id(self) -> str:
		return self.provider_id

	def is_enabled(self) -> bool:
		return self.enabled


class TestProviderRegistry(CetoTestSuite):
	def test_default_registry_pins_the_paygi_provider_ids(self):
		registry = default_registry()
		self.assertEqual(
			[tuple(str(provider.id) for provider in registry.providers())],
			[("pp_beam_beam", "pp_stripe_stripe")],
		)

	def test_registry_resolves_by_provider_id(self):
		registry = default_registry()
		self.assertEqual(registry.resolve("pp_stripe_stripe").gateway, "stripe")
		self.assertIsNone(registry.resolve("pp_unknown_unknown"))
		self.assertIsNone(registry.resolve(""))

	def test_registry_enabled_filters_disabled_providers(self):
		registry = ProviderRegistry(
			(
				EnabledProvider("pp_on_on", enabled=True),
				EnabledProvider("pp_off_off", enabled=False),
			)
		)
		self.assertEqual([provider.id for provider in registry.enabled()], ["pp_on_on"])

	def test_registry_enabled_is_empty_without_enabled_providers(self):
		registry = ProviderRegistry((EnabledProvider("pp_off_off", enabled=False),))
		self.assertEqual(registry.enabled(), ())


class TestPaygiProvider(CetoTestSuite):
	def test_paygi_absent_means_no_enabled_providers(self):
		# The defensive boundary: a site without paygi must answer "disabled"
		# without ever reading a settings row.
		with (
			patch("frappe.get_installed_apps", return_value=["frappe", "erpnext"]),
			patch("frappe.db.table_exists") as table_exists,
		):
			registry = default_registry()
			self.assertEqual(registry.enabled(), ())
		table_exists.assert_not_called()

	def test_missing_settings_table_means_disabled(self):
		provider = default_registry().resolve("pp_beam_beam")
		with (
			patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "paygi"]),
			patch("frappe.db.table_exists", return_value=False),
			patch("frappe.db.get_single_value") as get_single_value,
		):
			self.assertFalse(provider.is_enabled())
		get_single_value.assert_not_called()

	def test_enabled_settings_enable_the_provider(self):
		provider = default_registry().resolve("pp_beam_beam")
		with (
			patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "paygi"]),
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.get_single_value", return_value=1) as get_single_value,
		):
			self.assertTrue(provider.is_enabled())
		get_single_value.assert_called_once_with("Beam Settings", "enabled")

	def test_disabled_settings_disable_the_provider(self):
		for value in (0, None, "0"):
			with self.subTest(value=value):
				provider = default_registry().resolve("pp_stripe_stripe")
				with (
					patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "paygi"]),
					patch("frappe.db.table_exists", return_value=True),
					patch("frappe.db.get_single_value", return_value=value),
				):
					self.assertFalse(provider.is_enabled())

	def test_unreadable_settings_fail_closed_without_raising(self):
		provider = default_registry().resolve("pp_beam_beam")
		with (
			patch("frappe.get_installed_apps", return_value=["frappe", "erpnext", "paygi"]),
			patch("frappe.db.table_exists", return_value=True),
			patch("frappe.db.get_single_value", side_effect=Exception("unreadable schema")),
		):
			self.assertFalse(provider.is_enabled())

	def test_settings_reader_answers_the_enabled_switch(self):
		with patch("frappe.db.get_single_value", return_value=1):
			self.assertTrue(paygi_settings_enabled("Beam Settings"))

	def test_provider_id_follows_the_medusa_pp_convention(self):
		self.assertEqual(PaygiProvider("beam", "Beam Settings").id, "pp_beam_beam")
		self.assertEqual(PaygiProvider("stripe", "Stripe Settings").id, "pp_stripe_stripe")

	def test_registry_answers_the_pinned_store_provider_ids(self):
		# The ids the pinned StorePaymentProvider contract serves.
		registry = default_registry()
		self.assertEqual(
			{provider.id for provider in registry.providers()},
			{"pp_beam_beam", "pp_stripe_stripe"},
		)
		self.assertEqual({type(provider) for provider in registry.providers()}, {PaygiProvider})
