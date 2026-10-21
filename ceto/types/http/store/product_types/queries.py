"""Pinned query contracts of the Medusa Store Product Type routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreProductTypeListParams`` carries the ``FindParams`` pagination the
upstream list validator pins (``offset: 0`` / ``limit: 50``, recorded in
the manifest beside the Ceto read-model page bound
``PRODUCT_TYPE_LIST_MAX_LIMIT``) and ``StoreProductTypeParams`` is a bare
``SelectParams``.

The Ceto read-model bounds one page (``limit`` capped at the manifest
bound, both numbers non-negative), so a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped. The upstream
``q`` search, the ``id``/``value``/``external_id`` filters, the
``created_at``/``updated_at`` operator maps, the ``$and``/``$or``
combinators, the ``order`` sort expression and the ``fields`` selector are
deliberately absent and rejected as unknown fields
(``docs/catalog/endpoints.md``): the type projection exposes no selectable
surface beyond the pinned entity and one pinned ordering (by value), and a
client must never receive a page it cannot reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.product_types.manifest import (
	PRODUCT_TYPE_LIST_DEFAULT_LIMIT,
	PRODUCT_TYPE_LIST_DEFAULT_OFFSET,
	PRODUCT_TYPE_LIST_MAX_LIMIT,
)


class StoreProductTypeListParams(BaseModel):
	"""Query of ``GET /store/product-types``.

	Mirrors the pinned ``StoreProductTypeListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination. Unknown
	keys are rejected like on every core payload, and the pagination carries
	the Ceto read-model bounds: ``limit`` is the pinned default capped at one
	page's bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_TYPE_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_TYPE_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_TYPE_LIST_DEFAULT_OFFSET, ge=0)


class StoreProductTypeParams(BaseModel):
	"""Query of ``GET /store/product-types/{id}``.

	The pinned ``StoreProductTypeParams`` is a bare ``SelectParams`` upstream;
	Ceto serves no ``fields`` selector on the fixed projection yet, so the
	model accepts nothing and forbids everything: every key — including a
	``fields`` selector the fixed projection never applies — is refused as
	``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
