"""Provider-neutral shipping-option quote.

The one data shape every provider — the built-in ERPNext rules provider
as well as any ``ceto_shipping_providers`` registrant — returns to the
registry. The DTO stays domain-level on purpose: providers speak their
own option keys and resolved amounts, and only the API slice projects
onto the pinned ``StoreCartShippingOption`` entity (the ``so_`` id, the
provider relation, the calculated-price subset).

``amount`` is this cart's quote in the cart's currency, a plain float per
the repository money convention; ``is_tax_inclusive`` mirrors the Selling
charge row (no tax allocation). A provider that cannot resolve a rate for
a context contributes no quote rather than a fabricated zero.
"""

from dataclasses import dataclass
from typing import Literal

from ceto.services.shipping.errors import ShippingOptionError
from ceto.services.shipping.ids import OPTION_ID_SEPARATOR, encode_option_id


@dataclass(frozen=True, slots=True)
class ShippingOptionQuote:
	"""One provider's quote for one cart context."""

	provider_id: str
	option_key: str
	name: str
	amount: float
	currency: str
	price_type: Literal["flat", "calculated"] = "flat"
	is_tax_inclusive: bool = False
	data: dict | None = None
	metadata: dict | None = None

	@property
	def option_id(self) -> str:
		"""The public, opaque ``so_`` token minted from the identity."""
		return encode_option_id(self.provider_id, self.option_key)

	def __post_init__(self) -> None:
		if not isinstance(self.provider_id, str) or not self.provider_id.strip():
			raise ShippingOptionError("A shipping option quote requires a provider id")
		if OPTION_ID_SEPARATOR in self.provider_id:
			raise ShippingOptionError(f"A quote provider id cannot contain {OPTION_ID_SEPARATOR!r}")
		if not isinstance(self.option_key, str) or not self.option_key.strip():
			raise ShippingOptionError("A shipping option quote requires an option key")
