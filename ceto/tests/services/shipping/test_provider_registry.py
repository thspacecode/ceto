"""Focused tests for the deterministic shipping provider registry."""

import unittest
from unittest import mock

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.errors import MalformedShippingOptionIdError
from ceto.services.shipping.ids import encode_option_id
from ceto.services.shipping.options import ShippingOptionQuote
from ceto.services.shipping.providers.erpnext import PROVIDER_ID, ErpnextShippingRuleProvider
from ceto.services.shipping.registry import ShippingProviderRegistry

CONTEXT = ShippingQuoteContext(
	cart_id="cart_1",
	company="Ceto Test Co",
	company_currency="USD",
	currency="USD",
	conversion_rate=1.0,
	base_net_total=1500.0,
	total_net_weight=0.0,
)


def quote(provider_id: str, option_key: str, *, currency: str = "USD", amount: float = 10.0):
	return ShippingOptionQuote(
		provider_id=provider_id,
		option_key=option_key,
		name=option_key.title(),
		amount=amount,
		currency=currency,
	)


class StubProvider:
	"""A provider double with configurable behaviour."""

	def __init__(self, provider_id, quotes=(), *, error=None, with_get_option=False):
		self.id = provider_id
		self.quotes = list(quotes)
		self.error = error
		self.list_calls = 0
		self.get_calls = []
		if with_get_option:
			self.get_option = self._get_option

	def list_options(self, context):
		self.list_calls += 1
		if self.error:
			raise self.error
		return self.quotes

	def _get_option(self, context, option_key):
		self.get_calls.append(option_key)
		if self.error:
			raise self.error
		return next((q for q in self.quotes if q.option_key == option_key), None)


class HookedProvider:
	id = "hook.ok"

	def list_options(self, context):
		return []


class TestRegistryConstruction(unittest.TestCase):
	def test_registers_providers_in_order(self) -> None:
		registry = ShippingProviderRegistry([StubProvider("a"), StubProvider("b")])
		self.assertEqual([p.id for p in registry.providers()], ["a", "b"])

	def test_the_first_provider_claiming_an_id_wins(self) -> None:
		first, second = StubProvider("a", [quote("a", "one")]), StubProvider("a", [quote("a", "two")])
		registry = ShippingProviderRegistry([first, second])
		self.assertIs(registry.get("a"), first)
		self.assertEqual(len(registry.providers()), 1)

	def test_get_returns_none_for_unknown_ids(self) -> None:
		self.assertIsNone(ShippingProviderRegistry([]).get("nobody"))


class TestFromSite(unittest.TestCase):
	def test_registers_the_builtin_provider_without_hooks(self) -> None:
		with mock.patch("frappe.get_hooks", return_value=[]):
			registry = ShippingProviderRegistry.from_site()
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID])
		self.assertIsInstance(registry.get(PROVIDER_ID), ErpnextShippingRuleProvider)

	def test_appends_hook_providers_in_declaration_order(self) -> None:
		class HookedA:
			id = "hook.a"

			def list_options(self, context):
				return []

		def make_b():
			return HookedProvider()

		paths = {"app_a.providers.HookedA": HookedA, "app_b.factories.make_b": make_b}
		with (
			mock.patch("frappe.get_hooks", return_value=list(paths)),
			mock.patch("frappe.get_attr", side_effect=paths.get),
			mock.patch("frappe.log_error"),
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID, "hook.a", "hook.ok"])

	def test_a_ready_instance_registers_without_being_called(self) -> None:
		instance = StubProvider("hook.i")
		with (
			mock.patch("frappe.get_hooks", return_value=["app.mod.INSTANCE"]),
			mock.patch("frappe.get_attr", return_value=instance),
			mock.patch("frappe.log_error"),
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertIn(instance, registry.providers())

	def test_the_builtin_provider_cannot_be_displaced(self) -> None:
		# First registration wins: a downstream provider claiming the
		# built-in id is ignored, so the erpnext identity stays stable.
		usurper = StubProvider(PROVIDER_ID, [quote(PROVIDER_ID, "fake")])
		with (
			mock.patch("frappe.get_hooks", return_value=["app.usurper"]),
			mock.patch("frappe.get_attr", return_value=usurper),
			mock.patch("frappe.log_error"),
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertIsInstance(registry.get(PROVIDER_ID), ErpnextShippingRuleProvider)

	def test_an_unresolvable_path_is_isolated(self) -> None:
		def attr(path):
			if path == "broken.path":
				raise ImportError("no such module")
			return HookedProvider

		with (
			mock.patch("frappe.get_hooks", return_value=["broken.path", "app.providers.Hooked"]),
			mock.patch("frappe.get_attr", side_effect=attr),
			mock.patch("frappe.log_error") as log_error,
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID, "hook.ok"])
		self.assertIn("broken.path", log_error.call_args.kwargs["title"])

	def test_an_object_without_the_provider_shape_is_refused(self) -> None:
		class NotAProvider:
			pass

		with (
			mock.patch("frappe.get_hooks", return_value=["app.NotAProvider"]),
			mock.patch("frappe.get_attr", return_value=NotAProvider),
			mock.patch("frappe.log_error") as log_error,
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID])
		self.assertEqual(log_error.call_count, 1)

	def test_a_factory_that_raises_is_isolated(self) -> None:
		def boom():
			raise RuntimeError("factory down")

		with (
			mock.patch("frappe.get_hooks", return_value=["app.boom"]),
			mock.patch("frappe.get_attr", return_value=boom),
			mock.patch("frappe.log_error") as log_error,
		):
			registry = ShippingProviderRegistry.from_site()
		self.assertEqual([p.id for p in registry.providers()], [PROVIDER_ID])
		log_error.assert_called_once()


class TestListing(unittest.TestCase):
	def test_lists_quotes_in_provider_order(self) -> None:
		a = StubProvider("a", [quote("a", "one"), quote("a", "two")])
		b = StubProvider("b", [quote("b", "three")])
		registry = ShippingProviderRegistry([a, b])
		self.assertEqual(
			[q.option_id for q in registry.list_options(CONTEXT)],
			[q.option_id for q in a.quotes + b.quotes],
		)

	def test_a_failing_provider_contributes_nothing(self) -> None:
		a = StubProvider("a", error=RuntimeError("provider down"))
		b = StubProvider("b", [quote("b", "ok")])
		registry = ShippingProviderRegistry([a, b])
		with mock.patch("frappe.log_error") as log_error:
			listed = registry.list_options(CONTEXT)
		self.assertEqual([q.provider_id for q in listed], ["b"])
		log_error.assert_called_once()

	def test_protocol_violations_are_dropped(self) -> None:
		foreign = quote("somebody.else", "x")
		wrong_currency = quote("a", "y", currency="EUR")
		a = StubProvider("a", [foreign, wrong_currency, object(), quote("a", "ok")])
		registry = ShippingProviderRegistry([a])
		with mock.patch("frappe.log_error") as log_error:
			listed = registry.list_options(CONTEXT)
		self.assertEqual([q.option_key for q in listed], ["ok"])
		self.assertEqual(log_error.call_count, 3)

	def test_duplicate_option_ids_keep_the_first_quote(self) -> None:
		a = StubProvider("a", [quote("a", "dup", amount=1), quote("a", "dup", amount=2)])
		registry = ShippingProviderRegistry([a])
		self.assertEqual([q.amount for q in registry.list_options(CONTEXT)], [1])


class TestResolve(unittest.TestCase):
	def test_resolves_an_option_id_through_the_minting_provider(self) -> None:
		a = StubProvider("a", [quote("a", "one")], with_get_option=True)
		registry = ShippingProviderRegistry([a])
		self.assertEqual(registry.resolve_option(CONTEXT, encode_option_id("a", "one")), a.quotes[0])
		self.assertEqual(a.get_calls, ["one"])

	def test_resolves_by_scanning_for_providers_without_get_option(self) -> None:
		a = StubProvider("a", [quote("a", "one")])
		registry = ShippingProviderRegistry([a])
		self.assertEqual(registry.resolve_option(CONTEXT, encode_option_id("a", "one")), a.quotes[0])
		self.assertEqual(a.list_calls, 1)

	def test_unknown_providers_and_unserved_keys_resolve_to_none(self) -> None:
		registry = ShippingProviderRegistry([StubProvider("a", [quote("a", "one")])])
		self.assertIsNone(registry.resolve_option(CONTEXT, encode_option_id("nobody", "one")))
		self.assertIsNone(registry.resolve_option(CONTEXT, encode_option_id("a", "other")))

	def test_a_failing_single_read_is_isolated(self) -> None:
		a = StubProvider("a", [quote("a", "one")], error=RuntimeError("down"), with_get_option=True)
		registry = ShippingProviderRegistry([a])
		with mock.patch("frappe.log_error") as log_error:
			self.assertIsNone(registry.resolve_option(CONTEXT, encode_option_id("a", "one")))
		log_error.assert_called_once()

	def test_a_mismatched_quote_is_not_served(self) -> None:
		# A provider answering with another provider's identity must not
		# leak through the public id resolution.
		class LiarProvider(StubProvider):
			def _get_option(self, context, option_key):
				return quote("b", "other")

		liar = LiarProvider("a", with_get_option=True)
		registry = ShippingProviderRegistry([liar])
		with mock.patch("frappe.log_error"):
			self.assertIsNone(registry.resolve_option(CONTEXT, encode_option_id("a", "one")))

	def test_a_wrong_key_answer_is_not_served(self) -> None:
		class WrongKeyProvider(StubProvider):
			def _get_option(self, context, option_key):
				return quote("a", "other")

		registry = ShippingProviderRegistry([WrongKeyProvider("a", with_get_option=True)])
		self.assertIsNone(registry.resolve_option(CONTEXT, encode_option_id("a", "one")))

	def test_malformed_ids_raise_the_domain_error(self) -> None:
		registry = ShippingProviderRegistry([StubProvider("a")])
		with self.assertRaises(MalformedShippingOptionIdError):
			registry.resolve_option(CONTEXT, "Dev Flat Rate")


if __name__ == "__main__":
	unittest.main()
