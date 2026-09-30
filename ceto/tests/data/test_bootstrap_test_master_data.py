"""Tests for the shared test bootstrap behind ``ceto.tests.utils``.

Pins the three contracts integration tests rely on: ``ceto.tests.utils``
exports the suite and bootstraps at import time without import cycles, the
commerce baseline is reused from ``ceto.data.bootstrap_dev`` only, and reruns
converge to an all-skipped report.
"""

import os
import subprocess
import sys
from dataclasses import replace
from unittest.mock import patch

import erpnext
import frappe
from frappe.utils.password import check_password

import ceto.tests.data.bootstrap_test_master_data as bootstrap_module
from ceto.data.base_importer import BaseImporter, Report
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.tests.data.bootstrap_test_master_data import (
	TEST_CUSTOMER,
	TEST_CUSTOMER_PASSWORD,
	TEST_DISABLED_CUSTOMER,
	TEST_SYSTEM_USER,
	BootStrapTestMasterData,
)
from ceto.tests.utils import CetoTestSuite


def empty_report() -> Report:
	return {"created": {}, "updated": {}, "skipped": {}, "notes": []}


def require_company(test: CetoTestSuite) -> None:
	"""Skip unless the site offers the commerce baseline a usable Company.

	Mirrors ``BootStrapTestMasterData.resolve_baseline_settings``: the site
	default company is used as-is, and a lone unpinned Company is accepted
	because the bootstrap pins it. Zero or several companies without a
	default stay skipped, as ``bootstrap_dev`` reports them untouched.
	"""
	if erpnext.get_default_company():
		return
	companies = frappe.get_all("Company", pluck="name")
	if len(companies) == 1:
		return
	test.skipTest("No default or single Company; commerce baseline prerequisites are unavailable")


class TestBootstrapDevReuse(CetoTestSuite):
	def test_commerce_baseline_is_reused_from_bootstrap_dev_only(self):
		self.assertTrue(issubclass(bootstrap_module.SetupSite, BaseImporter))
		self.assertEqual(bootstrap_module.SetupSite.__module__, "ceto.data.bootstrap_dev.setup_site")


class TestMakeDelegates(CetoTestSuite):
	def test_make_runs_the_dev_baseline_before_the_test_auth_records(self):
		events = []
		report = empty_report() | {"created": {"Item": ["DEV-TSHIRT-001"]}}

		def run_baseline():
			events.append("commerce-baseline")
			return report

		def make_user(email, *, enabled, user_type):
			events.append(("user", email))

		def make_google_key():
			events.append("google-key")

		suite = BootStrapTestMasterData()
		with (
			patch.object(bootstrap_module, "SetupSite") as setup_site,
			patch.object(BootStrapTestMasterData, "make_user", side_effect=make_user),
			patch.object(BootStrapTestMasterData, "make_google_login_key", side_effect=make_google_key),
		):
			setup_site.return_value.make.side_effect = run_baseline
			returned = suite.make()

		setup_site.assert_called_once()
		self.assertIsInstance(setup_site.call_args[0][0], BootstrapSettings)
		setup_site.return_value.make.assert_called_once_with()
		self.assertEqual(
			events,
			[
				"commerce-baseline",
				("user", TEST_CUSTOMER),
				("user", TEST_DISABLED_CUSTOMER),
				("user", TEST_SYSTEM_USER),
				"google-key",
			],
		)
		self.assertIs(returned, suite.report)
		self.assertEqual(returned["created"]["Item"], ["DEV-TSHIRT-001"])

	def test_each_instance_reports_only_its_own_run(self):
		self.assertEqual(BootStrapTestMasterData().report, empty_report())


class TestBaselineCompanySettings(CetoTestSuite):
	def test_site_default_company_is_used_unchanged(self):
		with patch.object(bootstrap_module.erpnext, "get_default_company", return_value="Default Co"):
			settings = BootStrapTestMasterData().resolve_baseline_settings()

		self.assertEqual(settings, BootstrapSettings())

	def test_single_unpinned_company_is_pinned_for_the_baseline(self):
		with (
			patch.object(bootstrap_module.erpnext, "get_default_company", return_value=None),
			patch.object(bootstrap_module.frappe, "get_all", return_value=["Solo Co"]),
		):
			settings = BootStrapTestMasterData().resolve_baseline_settings()

		self.assertEqual(settings, replace(BootstrapSettings(), company="Solo Co"))

	def test_zero_or_several_companies_are_left_to_bootstrap_dev(self):
		for companies in ([], ["A Co", "B Co"]):
			with self.subTest(companies=companies):
				with (
					patch.object(bootstrap_module.erpnext, "get_default_company", return_value=None),
					patch.object(bootstrap_module.frappe, "get_all", return_value=companies),
				):
					settings = BootStrapTestMasterData().resolve_baseline_settings()

				self.assertEqual(settings, BootstrapSettings())


class TestRerunConvergence(CetoTestSuite):
	def test_second_run_creates_and_updates_nothing(self):
		require_company(self)

		baseline = BootStrapTestMasterData().make()
		rerun = BootStrapTestMasterData().make()

		self.assertEqual(rerun["created"], {})
		self.assertEqual(rerun["updated"], {})
		for section in ("created", "updated"):
			for doctype in baseline[section]:
				self.assertIn(doctype, rerun["skipped"], doctype)

	def test_baseline_records_match_the_expected_state(self):
		require_company(self)

		BootStrapTestMasterData().make()

		self.assertEqual(frappe.db.get_value("User", TEST_CUSTOMER, "user_type"), "Website User")
		self.assertEqual(frappe.db.get_value("User", TEST_CUSTOMER, "enabled"), 1)
		self.assertEqual(frappe.db.get_value("User", TEST_DISABLED_CUSTOMER, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("User", TEST_SYSTEM_USER, "user_type"), "System User")
		self.assertEqual(
			frappe.db.get_value("Social Login Key", "google", "client_id"),
			"ceto-test-google-client",
		)
		self.assertEqual(check_password(TEST_CUSTOMER, TEST_CUSTOMER_PASSWORD), TEST_CUSTOMER)
		self.assertTrue(frappe.get_all("Item", filters={"item_code": ("like", "DEV-%")}, limit=1))


class TestUtilsImportContract(CetoTestSuite):
	def test_importing_ceto_tests_utils_bootstraps_in_a_clean_interpreter(self):
		script = f"""
import frappe

frappe.init({frappe.local.site!r}, sites_path=".")
frappe.connect()

import ceto.tests.utils as utils

assert issubclass(utils.CetoTestSuite, __import__("unittest").TestCase)
print(type(utils.boot_strap_test_master_data).__name__)
print(sorted(utils.__all__))
"""
		# frappe.__file__ sits at <bench>/apps/frappe/frappe/__init__.py; the bench
		# root that owns sites/ is four levels up. Bench processes run with the
		# sites directory as cwd (frappe resolves site paths and logs relative to
		# it), so the clean interpreter must start there too.
		sites_dir = os.path.join(
			os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(frappe.__file__)))),
			"sites",
		)
		result = subprocess.run(
			[sys.executable, "-c", script],
			cwd=sites_dir,
			capture_output=True,
			text=True,
			timeout=50,
			check=False,
		)
		self.assertEqual(result.returncode, 0, result.stderr)
		lines = result.stdout.strip().splitlines()
		self.assertEqual(lines[-2], "BootStrapTestMasterData")
		self.assertEqual(lines[-1], str(["CetoTestSuite", "boot_strap_test_master_data"]))
