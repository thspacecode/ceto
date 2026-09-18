import frappe
from frappe.utils.password import update_password

TEST_CUSTOMER = "ceto.customer@example.com"
TEST_CUSTOMER_PASSWORD = "Correct Horse Battery Staple 42!"
TEST_DISABLED_CUSTOMER = "ceto.disabled@example.com"
TEST_SYSTEM_USER = "ceto.system@example.com"


class BootStrapTestMasterData:
	"""Create the reusable, committed records required by Ceto integration tests.

	The bootstrap is deliberately idempotent: an existing test site is brought back
	to the expected baseline instead of requiring an empty database.
	"""

	def __init__(self) -> None:
		self.report: dict[str, list[str]] = {"created": [], "updated": []}

	def make(self) -> dict[str, list[str]]:
		self.make_user(TEST_CUSTOMER, enabled=True, user_type="Website User")
		self.make_user(TEST_DISABLED_CUSTOMER, enabled=False, user_type="Website User")
		self.make_user(TEST_SYSTEM_USER, enabled=True, user_type="System User")
		self.make_google_login_key()
		frappe.db.commit()  # nosemgrep
		return self.report

	def make_user(self, email: str, *, enabled: bool, user_type: str) -> None:
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
			change_type = "updated"
		else:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = "Ceto Test"
			user.send_welcome_email = 0
			user.flags.no_welcome_mail = True
			change_type = "created"

		user.enabled = enabled
		user.user_type = user_type
		if user_type == "System User" and not any(row.role == "System Manager" for row in user.roles):
			user.append("roles", {"role": "System Manager"})
		user.save(ignore_permissions=True)
		update_password(email, TEST_CUSTOMER_PASSWORD, logout_all_sessions=False)
		self.report[change_type].append(f"User:{email}")

	def make_google_login_key(self) -> None:
		if frappe.db.exists("Social Login Key", "google"):
			login_key = frappe.get_doc("Social Login Key", "google")
			change_type = "updated"
		else:
			login_key = frappe.new_doc("Social Login Key")
			login_key.get_social_login_provider("Google", initialize=True)
			change_type = "created"

		login_key.enable_social_login = 0
		login_key.client_id = "ceto-test-google-client"
		login_key.client_secret = "ceto-test-google-secret"
		login_key.save(ignore_permissions=True)
		self.report[change_type].append("Social Login Key:google")
