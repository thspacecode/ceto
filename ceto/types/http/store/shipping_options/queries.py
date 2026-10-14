"""Pinned query contracts of the Medusa Store shipping-option routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreGetShippingOptionList`` is the cart-scoped list query — the pinned
list validator requires ``cart_id`` and defaults ``offset: 0`` with
``limit: 20`` (dead parameters, recorded in the manifest) — and the
calculate route validates a bare ``SelectParams``, for which the pinned
``HttpTypes`` publish no named type.

Ceto's read models are stricter than the pinned upstream validators, whose
unknown keys are stripped: both models are ``extra="forbid"``, so every
unsupported key fails as ``400 invalid_data`` instead of being dropped.
The list accepts exactly ``cart_id`` — the one scoping key the route
resolves — and refuses the dead ``FindParams`` pagination (the pinned route
ignores ``limit``/``offset`` and its non-paginated envelope cannot carry
them), the ``fields`` selector, the ``order`` sort, the ``$and``/``$or``
combinators and ``is_return``: ERPNext ``Selling`` rules have no return-rate
source, so no return option can ever be served.
"""

from pydantic import BaseModel, ConfigDict, Field


class StoreGetShippingOptionList(BaseModel):
	"""Query of ``GET /store/shipping-options``.

	Mirrors the pinned ``StoreGetShippingOptionList`` of
	``@medusajs/types@2.21.1`` reduced to the required ``cart_id`` scope.
	Unknown keys are rejected like on every core payload — including the
	pinned validator's dead pagination defaults (0/20, recorded in the
	manifest), ``is_return``, ``fields``, ``order`` and the
	``$and``/``$or`` combinators.
	"""

	model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

	cart_id: str = Field(min_length=1)


class StoreShippingOptionCalculateParams(BaseModel):
	"""Query of ``POST /store/shipping-options/{id}/calculate``.

	Upstream validates a bare ``SelectParams`` (the pinned ``HttpTypes``
	publish no named type and the pinned SDK sends no query). Ceto serves no
	``fields`` selector on the fixed projection, so the model accepts
	nothing and forbids everything: every key is refused as ``400
	invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
