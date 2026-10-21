"""Pinned query contracts of the Medusa Store Currency routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreGetCurrencyListParams`` carries the ``FindParams`` pagination the
upstream list validator pins (``offset: 0`` / ``limit: 50``, recorded in
the manifest beside the Ceto read-model page bound
``CURRENCY_LIST_MAX_LIMIT``) and ``StoreGetCurrencyParams`` is a bare
``SelectParams``.

The Ceto read-model bounds one page (``limit`` capped at the manifest
bound, both numbers non-negative), so a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped. The
upstream ``order`` sort expression and the ``fields`` selector are
deliberately absent and rejected as unknown fields
(``docs/reference-data/endpoints.md``): the scoped projection has no
selectable surface beyond the pinned entity, and a client must never
receive a page it cannot reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.currencies.manifest import (
	CURRENCY_LIST_DEFAULT_LIMIT,
	CURRENCY_LIST_DEFAULT_OFFSET,
	CURRENCY_LIST_MAX_LIMIT,
)


class StoreGetCurrencyListParams(BaseModel):
	"""Query of ``GET /store/currencies``.

	Mirrors the pinned ``StoreGetCurrencyListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination. Unknown
	keys are rejected like on every core payload, and the pagination carries
	the Ceto read-model bounds: ``limit`` is the pinned default capped at
	one page's bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=CURRENCY_LIST_DEFAULT_LIMIT, ge=0, le=CURRENCY_LIST_MAX_LIMIT)
	offset: int = Field(default=CURRENCY_LIST_DEFAULT_OFFSET, ge=0)


class StoreGetCurrencyParams(BaseModel):
	"""Query of ``GET /store/currencies/{code}``.

	The pinned ``StoreGetCurrencyParams`` is a bare ``SelectParams``
	upstream; Ceto serves no ``fields`` selector on the scoped projection
	yet, so the model accepts nothing and forbids everything: every key —
	including a ``fields`` selector the fixed projection never applies — is
	refused as ``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
