"""Provider core of the store shipping-option surface (Phase 4).

The components the pinned contract reserves for the behavior slice:

- :mod:`ceto.services.shipping.context` — the frozen quote context built
  from a cart's reference and Quotation.
- :mod:`ceto.services.shipping.options` — the provider-neutral quote DTO.
- :mod:`ceto.services.shipping.ids` — the reversible ``so_`` option-id
  codec.
- :mod:`ceto.services.shipping.errors` — the domain errors.
- :mod:`ceto.services.shipping.registry` — the deterministic provider
  registry (the built-in ERPNext provider plus the
  ``ceto_shipping_providers`` hook, with failure isolation).
- :mod:`ceto.services.shipping.erpnext_adapter` — the pure ERPNext
  ``Shipping Rule`` read adapter (eligibility and calculation).
- :mod:`ceto.services.shipping.providers` — the provider protocol and the
  built-in provider.
- :mod:`ceto.services.shipping.service` — the store orchestration that
  resolves the open cart, applies the publishable-key scope and projects
  the registry's quotes onto the pinned entities (the HTTP adapters in
  :mod:`ceto.api.store.shipping_options` stay thin over it).

The cart apply keeps accepting the legacy raw rule names.
"""

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.erpnext_adapter import (
	FIXED,
	NET_TOTAL,
	NET_WEIGHT,
	SELLING_RULE_TYPE,
	ShippingRuleCondition,
	ShippingRuleSet,
	eligible_rules,
	fetch_rule_sets,
	is_eligible_rule,
	rule_amount,
)
from ceto.services.shipping.errors import MalformedShippingOptionIdError, ShippingOptionError
from ceto.services.shipping.ids import (
	OPTION_ID_PREFIX,
	OPTION_ID_SEPARATOR,
	decode_option_id,
	encode_option_id,
)
from ceto.services.shipping.options import ShippingOptionQuote
from ceto.services.shipping.providers import (
	PROVIDER_ID,
	ErpnextShippingRuleProvider,
	OptionScanningProvider,
	ShippingProvider,
)
from ceto.services.shipping.registry import SHIPPING_PROVIDERS_HOOK, ShippingProviderRegistry
from ceto.services.shipping.service import ShippingOptionsService

__all__ = [
	"FIXED",
	"NET_TOTAL",
	"NET_WEIGHT",
	"OPTION_ID_PREFIX",
	"OPTION_ID_SEPARATOR",
	"PROVIDER_ID",
	"SELLING_RULE_TYPE",
	"SHIPPING_PROVIDERS_HOOK",
	"ErpnextShippingRuleProvider",
	"MalformedShippingOptionIdError",
	"OptionScanningProvider",
	"ShippingOptionError",
	"ShippingOptionQuote",
	"ShippingOptionsService",
	"ShippingProvider",
	"ShippingProviderRegistry",
	"ShippingQuoteContext",
	"ShippingRuleCondition",
	"ShippingRuleSet",
	"decode_option_id",
	"eligible_rules",
	"encode_option_id",
	"fetch_rule_sets",
	"is_eligible_rule",
	"rule_amount",
]
