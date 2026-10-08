"""Focused tests for the shared helpers on the Ceto test suite base."""

import uuid
from typing import TYPE_CHECKING

import frappe
from frappe.core.doctype.user.user import throttle_user_creation

from ceto.tests.testsuite import CetoTestSuite, bypass_user_creation_throttle

if TYPE_CHECKING:
	from frappe.model.document import Document


class TestBypassUserCreationThrottle(CetoTestSuite):
	def test_the_user_creation_throttle_trips_without_the_bypass(self) -> None:
		# Guards the premise: a zero limit throttles the very first insert
		# once a user was created "just now" (the seed below, uncommitted).
		with self.set_conf(throttle_user_limit=0):
			with bypass_user_creation_throttle():
				self._new_user().insert(ignore_permissions=True)
			self.assertRaises(frappe.ValidationError, self._insert_throttled_user)
			self.assertRaises(frappe.ValidationError, throttle_user_creation)

	def test_fixture_user_inserts_take_the_official_throttle_bypass(self) -> None:
		with self.set_conf(throttle_user_limit=0):
			with bypass_user_creation_throttle():
				# the seed makes the zero limit bite immediately
				self._new_user().insert(ignore_permissions=True)
				user = self._new_user()
				user.insert(ignore_permissions=True)

		self.assertTrue(frappe.db.exists("User", user.name))
		# the bypass only covers the throttled insert, not the doc defaults
		self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

	def test_the_bypass_flag_is_restored_when_the_scope_exits(self) -> None:
		self.assertFalse(frappe.flags.get("in_import"))

		with bypass_user_creation_throttle():
			self.assertTrue(frappe.flags.in_import)

		self.assertFalse(frappe.flags.get("in_import"))

	def test_a_previous_flag_value_survives_a_raising_scope(self) -> None:
		previous = frappe.flags.get("in_import")
		try:
			frappe.flags.in_import = True

			with self.assertRaises(RuntimeError), bypass_user_creation_throttle():
				raise RuntimeError("fixture failure")

			# restoration means the previous value, not a blind reset
			self.assertTrue(frappe.flags.get("in_import"))
		finally:
			frappe.flags.in_import = previous

	@staticmethod
	def _new_user() -> "Document":
		user = frappe.new_doc("User")
		user.email = f"ceto.tests.throttle.{uuid.uuid4().hex[:12]}@example.com"
		user.first_name = "Ceto Throttle Test"
		user.user_type = "Website User"
		user.enabled = 1
		user.send_welcome_email = 0
		return user

	def _insert_throttled_user(self) -> None:
		self._new_user().insert(ignore_permissions=True)
