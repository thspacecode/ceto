from unittest.mock import patch

import frappe

from ceto.services.carts.quotation import CartService
from ceto.services.common import privileged_scope
from ceto.tests.data.cart_test_data import CartTestData
from ceto.tests.utils import CetoTestSuite
from ceto.types.http.store.carts import StoreCreateCart


class ScopeInterrupt(Exception):
	"""Unwind a scope from the test body."""


class TestPrivilegedScope(CetoTestSuite):
	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.masters = CartTestData()
		# Frappe throttles user creation per hour; the exception case creates
		# its own user, so lift it in memory like the sibling suites.
		self._previous_throttle = frappe.local.conf.get("throttle_user_limit")
		frappe.local.conf["throttle_user_limit"] = 100000

	def tearDown(self) -> None:
		if self._previous_throttle is None:
			frappe.local.conf.pop("throttle_user_limit", None)
		else:
			frappe.local.conf["throttle_user_limit"] = self._previous_throttle
		super().tearDown()

	def test_scope_assumes_administrator_inside_and_restores_on_success(self) -> None:
		with self.set_user("Guest"):
			with privileged_scope():
				self.assertEqual(frappe.session.user, "Administrator")
				self.assertTrue(frappe.flags.ignore_permissions)
			# The exact prior user and flag come back after the scope.
			self.assertEqual(frappe.session.user, "Guest")
			self.assertIsNone(frappe.flags.ignore_permissions)
		self.assertEqual(frappe.session.user, "Administrator")
		self.assertIsNone(frappe.flags.ignore_permissions)

	def test_scope_restores_prior_user_and_flag_on_exception(self) -> None:
		with self.set_create_user() as email:
			with self.assertRaises(ScopeInterrupt), privileged_scope():
				self.assertEqual(frappe.session.user, "Administrator")
				self.assertTrue(frappe.flags.ignore_permissions)
				raise ScopeInterrupt
			self.assertEqual(frappe.session.user, email)
			self.assertIsNone(frappe.flags.ignore_permissions)

	def test_scope_restores_unset_flag_on_success_and_exception(self) -> None:
		with privileged_scope():
			self.assertEqual(frappe.session.user, "Administrator")
			self.assertTrue(frappe.flags.ignore_permissions)
		self.assertEqual(frappe.session.user, "Administrator")
		self.assertIsNone(frappe.flags.ignore_permissions)

		with self.assertRaises(ScopeInterrupt), privileged_scope():
			raise ScopeInterrupt
		self.assertEqual(frappe.session.user, "Administrator")
		self.assertIsNone(frappe.flags.ignore_permissions)

	def test_nested_scopes_restore_the_exact_prior_user_and_flag(self) -> None:
		with self.set_user("Guest"), self.set_flags(ignore_permissions=True):
			with privileged_scope():
				with privileged_scope():
					self.assertEqual(frappe.session.user, "Administrator")
					self.assertTrue(frappe.flags.ignore_permissions)
				# The inner exit restores the outer scope's exact values.
				self.assertEqual(frappe.session.user, "Administrator")
				self.assertTrue(frappe.flags.ignore_permissions)
			# The outer exit restores the caller's exact values.
			self.assertEqual(frappe.session.user, "Guest")
			self.assertTrue(frappe.flags.ignore_permissions)
		self.assertEqual(frappe.session.user, "Administrator")
		self.assertIsNone(frappe.flags.ignore_permissions)

	def test_inner_scope_exception_keeps_outer_scope_active(self) -> None:
		with self.set_user("Guest"):
			with privileged_scope():
				with self.assertRaises(ScopeInterrupt), privileged_scope():
					raise ScopeInterrupt
				# The outer scope still elevates after the inner unwind.
				self.assertEqual(frappe.session.user, "Administrator")
				self.assertTrue(frappe.flags.ignore_permissions)
			self.assertEqual(frappe.session.user, "Guest")
			self.assertIsNone(frappe.flags.ignore_permissions)

	def test_guest_cannot_save_the_quotation_outside_the_scope(self) -> None:
		with self.set_conf(ceto_cart=self.masters.configuration):
			_, quotation = CartService().create(StoreCreateCart(email="guest@example.com"))

		with self.set_user("Guest"):
			# The scope left no elevation behind: the exact prior guest
			# session and the unset flag are restored.
			self.assertEqual(frappe.session.user, "Guest")
			self.assertIsNone(frappe.flags.ignore_permissions)

			quotation = frappe.get_doc("Quotation", quotation.name)
			with self.assertRaises(frappe.PermissionError):
				quotation.save()

	def test_user_creation_survives_a_site_above_the_default_throttle(self) -> None:
		# Late in the full suite on an unmodified site the shared
		# creation count already rides above the default limit.
		with patch.object(frappe.db, "get_creation_count", return_value=1000):
			with self.set_create_user() as email:
				self.assertTrue(frappe.db.exists("User", email))
