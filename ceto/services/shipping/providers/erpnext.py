"""The built-in shipping provider: ERPNext ``Shipping Rule`` masters.

Every enabled ``Selling`` rule of the cart's company serves one option:
the option key is the rule name (the same master identity the cart apply
accepts as the legacy raw id), the served name is the rule label, and the
amount is the ERPNext-resolved rate for the cart's context in the cart's
currency (:mod:`ceto.services.shipping.erpnext_adapter`). ``price_type``
is always the pinned ``flat`` — every option is a deterministic
cart-specific quote, never a stored list price — and ``is_tax_inclusive``
stays ``False`` because the Selling charge row books without tax
allocation.

The provider is registered first by the registry and cannot be displaced:
a downstream app registering the same id is ignored (first registration
wins), so the ``erpnext`` identity always means this provider.
"""

from collections.abc import Sequence

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.erpnext_adapter import eligible_rules, fetch_rule_sets, rule_amount
from ceto.services.shipping.options import ShippingOptionQuote
from ceto.services.shipping.providers.base import OptionScanningProvider

PROVIDER_ID = "erpnext"


class ErpnextShippingRuleProvider(OptionScanningProvider):
	"""Serve the cart company's enabled ``Selling`` Shipping Rules."""

	@property
	def id(self) -> str:
		return PROVIDER_ID

	def list_options(self, context: ShippingQuoteContext) -> Sequence[ShippingOptionQuote]:
		return [
			ShippingOptionQuote(
				provider_id=self.id,
				option_key=rule.name,
				name=rule.label,
				amount=rule_amount(rule, context),
				currency=context.currency,
			)
			for rule in eligible_rules(fetch_rule_sets(context.company), context)
		]
