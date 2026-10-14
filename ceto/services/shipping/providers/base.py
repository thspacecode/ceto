"""The shipping provider protocol and its scanning convenience base.

A shipping provider serves option quotes for one cart context: it owns a
provider id (the left side of the ``so_`` token) and its own option-key
namespace (the right side). ``list_options`` returns every quote the
provider serves for the context; ``get_option`` resolves a single key.
Providers only read — a quote is computed from the context and the
provider's own masters, never written back to the cart.

``get_option`` is optional in the protocol: the registry resolves single
keys by scanning ``list_options`` for providers that do not define it.
:class:`OptionScanningProvider` bakes that default in for class-based
providers.
"""

import abc
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.options import ShippingOptionQuote


@runtime_checkable
class ShippingProvider(Protocol):
	"""The minimal shape every shipping provider satisfies."""

	@property
	def id(self) -> str: ...

	def list_options(self, context: ShippingQuoteContext) -> Sequence[ShippingOptionQuote]: ...


class OptionScanningProvider(abc.ABC):
	"""Base for class-based providers: single reads scan the listing."""

	@property
	@abc.abstractmethod
	def id(self) -> str: ...

	@abc.abstractmethod
	def list_options(self, context: ShippingQuoteContext) -> Sequence[ShippingOptionQuote]: ...

	def get_option(self, context: ShippingQuoteContext, option_key: str) -> ShippingOptionQuote | None:
		"""Return the provider's quote for ``option_key``, or ``None``."""
		for quote in self.list_options(context):
			if quote.option_key == option_key:
				return quote
		return None
