"""Domain errors of the shipping-options provider core.

The provider core stays decoupled from the HTTP layer: the API slice maps
these domain errors onto Medusa-compatible responses when the routes land.
An undecodable option id is the only caller-facing condition — it is
request data, never a server fault. Every other failure (a provider
crashing, a registry miss) is expressed through ``None`` results and
failure isolation, so one broken provider can never fail option listing.
"""


class ShippingOptionError(Exception):
	"""Base error of the shipping-options provider subsystem."""


class MalformedShippingOptionIdError(ShippingOptionError):
	"""A public option id is not a decodable ``so_`` token."""
