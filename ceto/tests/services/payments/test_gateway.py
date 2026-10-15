"""The paygi charge boundary: exact minor units and stable failure.

The wrapper is the only Ceto code that may call paygi's ``create_payment``.
Its contract: the conversion to ``amount_minor`` is exact ``Decimal`` math
over the currency master's ``fraction_units`` and refuses ambiguous amounts;
provider absence (paygi not installed) and any provider failure collapse
into the stable "no charge" ``None`` — never a raised error — with the
gateway name resolved from the pinned ``pp_<gateway>_<gateway>`` ids.

paygi is deliberately not installed on the test site (the registry treats
that as "no enabled providers"), so the stubs here inject a fake
``paygi.api`` module into ``sys.modules`` — the same lazy-import seam the
wrapper uses.
"""

import sys
import types
from contextlib import contextmanager
from unittest.mock import patch

import frappe

from ceto.services.common import privileged_scope
from ceto.services.payments.gateway import (
	ProviderChargeRequest,
	create_payment,
	gateway_for,
	to_minor_units,
)
from ceto.tests.utils import CetoTestSuite


def charge_request(**overrides) -> ProviderChargeRequest:
	values = {
		"session_id": "payses_test0000000000000000000000000001",
		"gateway": "beam",
		"amount": 100.0,
		"currency_code": "thb",
		"data": None,
	}
	values.update(overrides)
	return ProviderChargeRequest(**values)


@contextmanager
def paygi_api(stub):
	"""Install a fake ``paygi.api`` module whose ``create_payment`` is ``stub``."""
	module = types.ModuleType("paygi.api")
	module.create_payment = stub
	with patch.dict(sys.modules, {"paygi": types.ModuleType("paygi"), "paygi.api": module}):
		yield module


class TestMinorUnitConversion(CetoTestSuite):
	def test_two_decimal_currencies_convert_exactly(self):
		self.assertEqual(to_minor_units(100.0, "thb"), 10_000)
		self.assertEqual(to_minor_units(100.0, "USD"), 10_000)
		self.assertEqual(to_minor_units(0.01, "thb"), 1)
		self.assertEqual(to_minor_units(1234.56, "thb"), 123_456)
		self.assertEqual(to_minor_units(19.99, "thb"), 1999)
		self.assertEqual(to_minor_units(0.07, "thb"), 7)

	def test_the_currency_master_divides(self):
		# KWD-style three-decimal money: the master's fraction_units (1000)
		# decides, not a hardcoded 100.
		name = "Ceto Test Minor Unit Fils"
		frappe.get_doc(
			{"doctype": "Currency", "currency_name": name, "fraction_units": 1000, "enabled": 1}
		).insert(ignore_permissions=True)
		self.assertEqual(to_minor_units(1.5, name), 1500)
		self.assertEqual(to_minor_units(1.234, name), 1234)
		with self.assertRaises(ValueError):
			to_minor_units(1.2345, name)

	def test_amounts_beyond_the_minor_unit_are_refused(self):
		# A cart total with sub-satang precision must never silently round
		# into a charge for a different amount — float noise included.
		for amount in (1.005, 0.1 + 0.2):
			with self.subTest(amount=amount):
				with self.assertRaises(ValueError):
					to_minor_units(amount, "thb")

	def test_non_positive_and_broken_amounts_are_refused(self):
		for amount in (0, -1, -0.01):
			with self.subTest(amount=amount):
				with self.assertRaises(ValueError):
					to_minor_units(amount, "thb")
		with self.assertRaises(ValueError):
			to_minor_units(float("nan"), "thb")
		with self.assertRaises(ValueError):
			to_minor_units(float("inf"), "thb")

	def test_unknown_currency_falls_back_to_two_decimals(self):
		self.assertEqual(to_minor_units(1.0, "ZZZ"), 100)


class TestGatewayNaming(CetoTestSuite):
	def test_pinned_ids_resolve_their_paygi_gateway(self):
		self.assertEqual(gateway_for("pp_beam_beam"), "beam")
		self.assertEqual(gateway_for("pp_stripe_stripe"), "stripe")

	def test_unknown_registry_ids_still_name_a_gateway_for_the_boundary(self):
		# The boundary forwards the name; paygi rejects unsupported ones, and
		# the wrapper's stable failure absorbs that instead of crashing.
		self.assertEqual(gateway_for("pp_unknown_unknown"), "unknown")


class TestStableWrapper(CetoTestSuite):
	def test_paygi_absence_is_a_stable_no_charge(self):
		# The lazy paygi import failing (app not installed) must not raise.
		self.assertIsNone(create_payment(charge_request()))

	def test_provider_failure_is_a_stable_no_charge(self):
		def failing(*args, **kwargs):
			raise frappe.ValidationError("gateway exploded")

		with paygi_api(failing):
			self.assertIsNone(create_payment(charge_request()))

	def test_conversion_failure_is_a_stable_no_charge(self):
		calls = []

		def spy(*args, **kwargs):
			calls.append(1)
			return {}

		with paygi_api(spy):
			self.assertIsNone(create_payment(charge_request(amount=1.005)))
		# The ambiguous amount never reaches paygi.
		self.assertEqual(calls, [])

	def test_the_charge_is_idempotent_by_session_and_privileged(self):
		observed = {}

		def fake_create_payment(
			provider,
			reference_doctype,
			reference_name,
			amount_minor,
			currency,
			idempotency_key=None,
			payment_method=None,
			**kwargs,
		):
			observed.update(
				{
					"provider": provider,
					"reference_doctype": reference_doctype,
					"reference_name": reference_name,
					"amount_minor": amount_minor,
					"currency": currency,
					"idempotency_key": idempotency_key,
					"payment_method": payment_method,
					"user": frappe.session.user,
				}
			)
			return {"payment_id": "attempt_1", "status": "Pending"}

		frappe.set_user("Guest")
		try:
			with paygi_api(fake_create_payment):
				response = create_payment(
					charge_request(data={"type": "QR"}, currency_code="thb", amount=100.0)
				)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(response, {"payment_id": "attempt_1", "status": "Pending"})
		self.assertEqual(observed["provider"], "beam")
		self.assertEqual(observed["reference_doctype"], "Ceto Payment Session")
		self.assertEqual(observed["reference_name"], observed["idempotency_key"])
		self.assertEqual(observed["amount_minor"], 10_000)
		# The session's stored ISO code passes through; paygi normalizes its
		# case at its own boundary.
		self.assertEqual(observed["currency"], "thb")
		self.assertEqual(observed["payment_method"], {"type": "QR"})
		# paygi requires a signed-in reader of the reference; checkout runs
		# as Guest, so the wrapper — and only the wrapper — elevates.
		self.assertEqual(observed["user"], "Administrator")

	def test_privileged_scope_restores_the_session_user(self):
		frappe.set_user("Guest")
		try:
			with privileged_scope():
				pass
			self.assertEqual(frappe.session.user, "Guest")
		finally:
			frappe.set_user("Administrator")
