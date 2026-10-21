"""Reference locales: enabled Frappe Languages plus the deterministic default.

``LocaleDirectory`` projects the enabled ``Language`` records onto the pinned
``StoreLocale`` shape, ordered by code, and resolves ``default_locale``
(the labeled Ceto extension) through the documented chain: configured
``ceto_cart.default_locale`` → enabled site language → enabled ``en`` →
first enabled code → ``None``.
"""

import frappe

from ceto.services.reference.locales import FALLBACK_LOCALE, LocaleDirectory
from ceto.tests.utils import CetoTestSuite

TEMP_LANGUAGES = ("zz_test", "aa_test")


class TestLocaleDirectory(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def test_lists_enabled_languages_ordered_by_code(self):
		with self.set_conf(ceto_cart={}):
			page = LocaleDirectory().list()
		codes = [locale.code for locale in page.locales]
		self.assertIn(FALLBACK_LOCALE, codes)
		self.assertEqual(codes, sorted(codes))
		english = next(locale for locale in page.locales if locale.code == FALLBACK_LOCALE)
		self.assertTrue(english.name)

	def test_disabled_languages_are_never_listed(self):
		self._insert_language(TEMP_LANGUAGES[0])
		with self.set_conf(ceto_cart={}):
			codes = [locale.code for locale in LocaleDirectory().list().locales]
			self.assertIn(TEMP_LANGUAGES[0], codes)
			frappe.db.set_value("Language", TEMP_LANGUAGES[0], "enabled", 0, update_modified=False)
			codes = [locale.code for locale in LocaleDirectory().list().locales]
		self.assertNotIn(TEMP_LANGUAGES[0], codes)

	def test_configured_default_locale_wins_when_enabled(self):
		with self.set_conf(ceto_cart={"default_locale": "fr"}):
			page = LocaleDirectory().list()
		self.assertIn("fr", [locale.code for locale in page.locales])
		self.assertEqual(page.default_locale, "fr")

	def test_unenabled_configured_default_falls_back_to_the_site_language(self):
		site_language = frappe.db.get_single_value("System Settings", "language") or FALLBACK_LOCALE
		with self.set_conf(ceto_cart={"default_locale": "zz_missing"}):
			page = LocaleDirectory().list()
		self.assertEqual(page.default_locale, site_language)

	def test_unset_configuration_falls_back_to_the_site_language(self):
		site_language = frappe.db.get_single_value("System Settings", "language") or FALLBACK_LOCALE
		with self.set_conf(ceto_cart={}):
			page = LocaleDirectory().list()
		self.assertEqual(page.default_locale, site_language)

	def test_the_chain_ends_at_the_first_enabled_code_then_none(self):
		for code in TEMP_LANGUAGES:
			self._insert_language(code)
		enabled = self._solo_languages(reversed(TEMP_LANGUAGES))
		with self.set_conf(ceto_cart={"default_locale": "zz_missing"}):
			page = LocaleDirectory().list()
		self.assertEqual([locale.code for locale in page.locales], sorted(enabled))
		# Neither the configured default nor the site language nor ``en``
		# is enabled: the first enabled code is the deterministic default.
		self.assertEqual(page.default_locale, sorted(enabled)[0])

		self._solo_languages(())
		with self.set_conf(ceto_cart={"default_locale": "zz_missing"}):
			page = LocaleDirectory().list()
		self.assertEqual(page.locales, [])
		self.assertIsNone(page.default_locale)

	def _enabled_languages(self) -> list[str]:
		return frappe.get_all("Language", filters={"enabled": 1}, pluck="name")

	def _insert_language(self, code: str) -> None:
		if not frappe.db.exists("Language", code):
			frappe.get_doc(
				{
					"doctype": "Language",
					"__newname": code,
					"language_code": code,
					"language_name": f"Ceto Test {code}",
					"enabled": 1,
				}
			).insert()

	def _solo_languages(self, codes) -> list[str]:
		"""Flip the enabled set to exactly ``codes`` inside the transaction."""
		self._previous_enabled = self._enabled_languages()
		enabled = list(codes)
		for code in set(self._previous_enabled) - set(enabled):
			frappe.db.set_value("Language", code, "enabled", 0, update_modified=False)
		for code in enabled:
			frappe.db.set_value("Language", code, "enabled", 1, update_modified=False)
		return enabled
