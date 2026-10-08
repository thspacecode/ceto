from dataclasses import replace

import erpnext
import frappe
from frappe.utils.password import check_password, update_password

from ceto.data.base_importer import BaseImporter, Report, apply_values, values_differ
from ceto.data.bootstrap_dev.settings import BootstrapSettings
from ceto.data.bootstrap_dev.setup_site import SetupSite
from ceto.tests.testsuite import bypass_user_creation_throttle

TEST_CUSTOMER = "ceto.customer@example.com"
TEST_CUSTOMER_PASSWORD = "Correct Horse Battery Staple 42!"
TEST_DISABLED_CUSTOMER = "ceto.disabled@example.com"
TEST_SYSTEM_USER = "ceto.system@example.com"


class BootStrapTestMasterData(BaseImporter):
	"""Create the reusable, committed records required by Ceto integration tests.

	The commerce baseline is reused verbatim from ``ceto.data.bootstrap_dev``,
	the only bootstrap layer Ceto ships; this class only layers the extra
	authentication records integration tests need. The bootstrap is
	deliberately idempotent: an existing test site is brought back to the
	expected baseline instead of requiring an empty database, and a rerun
	only converges drifted fields.

	Importers never commit, so — as the caller — this bootstrap commits its
	baseline once at the end of ``make``; the baseline must survive the
	per-test rollbacks of the surrounding test run.
	"""

	def make(self) -> Report:
		self.merge_report(SetupSite(self.resolve_baseline_settings()).make())
		self.make_user(TEST_CUSTOMER, enabled=True, user_type="Website User")
		self.make_user(TEST_DISABLED_CUSTOMER, enabled=False, user_type="Website User")
		self.make_user(TEST_SYSTEM_USER, enabled=True, user_type="System User")
		self.make_google_login_key()
		frappe.db.commit()  # nosemgrep
		return self.report

	def resolve_baseline_settings(self) -> BootstrapSettings:
		"""Pin the commerce company when the site default is unset but unambiguous.

		``bootstrap_dev`` resolves the target company from the site default and
		aborts loudly otherwise. The only avoidable blocker for tests is a
		usable site that never recorded a default company while holding exactly
		one Company; pinning it here mirrors what an operator would do through
		the documented ``company`` setting. Sites with zero or several
		companies stay untouched so ``bootstrap_dev`` keeps reporting them.
		"""
		settings = BootstrapSettings()
		if erpnext.get_default_company():
			return settings
		companies = frappe.get_all("Company", pluck="name")
		if len(companies) == 1:
			return replace(settings, company=companies[0])
		return settings

	def make_user(self, email: str, *, enabled: bool, user_type: str) -> None:
		owned_fields = {"enabled": enabled, "user_type": user_type}
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
			created = False
			changed = apply_values(user, owned_fields)
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = "Ceto Test"
			user.send_welcome_email = 0
			user.flags.no_welcome_mail = True
			created = True
			changed = True

		if user_type == "System User" and not any(row.role == "System Manager" for row in user.roles):
			user.append("roles", {"role": "System Manager"})
			changed = True

		if created:
			with bypass_user_creation_throttle():
				self.create_and_record(user, owned_fields, "User", email)
		elif changed:
			user.save(ignore_permissions=True)
			self.record_change("updated", "User", email)
		else:
			self.record_change("skipped", "User", email)
		self.ensure_password(email)

	def ensure_password(self, email: str) -> None:
		"""Set the shared test password only when it does not already verify."""
		try:
			check_password(email, TEST_CUSTOMER_PASSWORD, delete_tracker_cache=False)
		except frappe.AuthenticationError:
			update_password(email, TEST_CUSTOMER_PASSWORD, logout_all_sessions=False)

	def make_google_login_key(self) -> None:
		owned_fields = {
			"enable_social_login": 0,
			"client_id": "ceto-test-google-client",
			"client_secret": "ceto-test-google-secret",
		}
		if frappe.db.exists("Social Login Key", "google"):
			login_key = frappe.get_doc("Social Login Key", "google")
			# client_secret is masked on read, so verify it through its decrypted value.
			plain_fields = {k: v for k, v in owned_fields.items() if k != "client_secret"}
			changed = apply_values(login_key, plain_fields)
			stored_secret = login_key.get_password("client_secret", raise_exception=False)
			changed = values_differ(stored_secret, owned_fields["client_secret"]) or changed
			if changed:
				self.update_and_record(login_key, owned_fields, "Social Login Key", "google")
			else:
				self.record_change("skipped", "Social Login Key", "google")
		else:
			login_key = frappe.new_doc("Social Login Key")
			login_key.get_social_login_provider("Google", initialize=True)
			self.create_and_record(login_key, owned_fields, "Social Login Key", "google")
