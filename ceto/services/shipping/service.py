"""Store shipping-options orchestration (the Medusa shipping-option surface).

Composes the provider core with the cart read models: the service resolves
one open cart through the shared cart access — unknown, claimed-elsewhere
and non-open carts are the same masked ``404 not_found`` — applies the
caller's publishable-key scope through the ``guard`` seam the cart surface
uses, builds the frozen quote context from the resolved records and lets the
site's provider registry (:class:`~ceto.services.shipping.registry.ShippingProviderRegistry`)
serve. Every contributed quote projects onto the pinned
``StoreCartShippingOption`` entity — the opaque ``so_`` id, the provider
relation reduced to its two columns and the calculated-price subset filled
from the quote itself.

Reads only: listing and calculating never write the cart, ``is_return``
serves the honest empty set instead of an error, and every option that no
registered provider serves for the cart — an unknown, foreign, malformed or
ineligible id — is the same masked ``404 not_found``, so the option space
stays opaque and one broken provider can never fail a read.
"""

from collections.abc import Callable
from typing import TYPE_CHECKING

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.access import CartAccess
from ceto.services.shipping.context import ShippingQuoteContext
from ceto.services.shipping.errors import MalformedShippingOptionIdError
from ceto.services.shipping.options import ShippingOptionQuote
from ceto.services.shipping.registry import ShippingProviderRegistry
from ceto.types.http.store.shipping_options import (
	StoreCartShippingOption,
	StoreShippingOptionCalculatedPrice,
	StoreShippingOptionListResponse,
	StoreShippingOptionProvider,
	StoreShippingOptionResponse,
)

if TYPE_CHECKING:
	from frappe.model.document import Document


class ShippingOptionsService:
	"""List a cart's shipping options and calculate one option's price."""

	def __init__(
		self,
		access: CartAccess | None = None,
		registry: ShippingProviderRegistry | None = None,
	) -> None:
		self.access = access or CartAccess()
		self._registry = registry

	def list(
		self,
		cart_id: str,
		*,
		is_return: bool | None = None,
		guard: Callable[["Document"], None] | None = None,
	) -> StoreShippingOptionListResponse:
		"""Return the pinned ``{shipping_options}`` envelope of ``cart_id``.

		``guard`` runs against the resolved reference before anything is
		priced, exactly like the cart mutations scope their key. The cart
		resolves first: ``is_return=true`` serves the empty option set —
		ERPNext ``Selling`` rules have no return-rate source — but a masked
		cart is ``404 not_found`` either way.
		"""
		reference, quotation = self._cart(cart_id, guard)
		if is_return:
			return StoreShippingOptionListResponse(shipping_options=[])
		context = ShippingQuoteContext.from_cart(reference, quotation)
		options = [self._option(quote) for quote in self.providers.list_options(context)]
		return StoreShippingOptionListResponse(shipping_options=options)

	def calculate(
		self,
		cart_id: str,
		option_id: str,
		*,
		guard: Callable[["Document"], None] | None = None,
	) -> StoreShippingOptionResponse:
		"""Return the pinned ``{shipping_option}`` of ``option_id`` on ``cart_id``.

		The id is resolved through the registry against this cart's context:
		a token no registered provider serves for the cart — unknown,
		disabled, foreign-company, country-ineligible or not a ``so_`` token
		at all — is the same masked ``404 not_found`` as an unknown cart.
		"""
		reference, quotation = self._cart(cart_id, guard)
		context = ShippingQuoteContext.from_cart(reference, quotation)
		try:
			quote = self.providers.resolve_option(context, option_id)
		except MalformedShippingOptionIdError:
			quote = None
		if quote is None:
			raise RouteNotFoundError(f"Shipping option {option_id or '(not set)'} not found")
		return StoreShippingOptionResponse(shipping_option=self._option(quote))

	@property
	def providers(self) -> ShippingProviderRegistry:
		"""The site's provider registry, built per read from the live hooks."""
		return self._registry or ShippingProviderRegistry.from_site()

	def _cart(
		self, cart_id: str, guard: Callable[["Document"], None] | None
	) -> tuple["Document", "Document"]:
		"""Resolve the open cart of ``cart_id`` and apply the key scope."""
		reference, quotation = self.access.get(cart_id)
		if guard is not None:
			guard(reference)
		return reference, quotation

	def _option(self, quote: ShippingOptionQuote) -> StoreCartShippingOption:
		"""Project one provider quote onto the pinned option entity."""
		return StoreCartShippingOption(
			id=quote.option_id,
			name=quote.name,
			price_type=quote.price_type,
			provider=StoreShippingOptionProvider(id=quote.provider_id, is_enabled=True),
			amount=quote.amount,
			is_tax_inclusive=quote.is_tax_inclusive,
			calculated_price=StoreShippingOptionCalculatedPrice(
				calculated_amount=quote.amount,
				original_amount=quote.amount,
				currency_code=quote.currency.lower(),
				is_calculated_price_tax_inclusive=quote.is_tax_inclusive,
			),
			data=quote.data,
			metadata=quote.metadata,
		)
