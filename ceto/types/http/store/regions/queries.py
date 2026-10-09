"""Pinned query contracts of the Medusa Store Region routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreRegionFilters`` carries the ``FindParams`` pagination the upstream
list validator pins (``offset: 0`` / ``limit: 20``, recorded in the
manifest beside the Ceto read-model page bound
``REGION_LIST_MAX_LIMIT``) and ``StoreGetRegionParams`` is a bare
``SelectParams``.

The Ceto read-model bounds one page (``limit`` capped at the manifest
bound, both numbers non-negative), so a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped. The
upstream ``q`` search, ``$and``/``$or`` combinators, ``order`` sort
expression and the ``fields`` selector are deliberately absent and
rejected as unknown fields (``docs/reference-data/endpoints.md``): the
config-backed projection has no searchable column and no selectable
surface beyond the pinned entity, and a client must never receive a page
it cannot reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.regions.manifest import (
	REGION_LIST_DEFAULT_LIMIT,
	REGION_LIST_DEFAULT_OFFSET,
	REGION_LIST_MAX_LIMIT,
)


class StoreRegionFilters(BaseModel):
	"""Query of ``GET /store/regions``.

	Mirrors the pinned ``StoreRegionFilters`` of ``@medusajs/types@2.21.1``
	with the ``FindParams`` pagination. Unknown keys are rejected like on
	every core payload, and the pagination carries the Ceto read-model
	bounds: ``limit`` is the pinned default capped at one page's bulk load,
	``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=REGION_LIST_DEFAULT_LIMIT, ge=0, le=REGION_LIST_MAX_LIMIT)
	offset: int = Field(default=REGION_LIST_DEFAULT_OFFSET, ge=0)


class StoreGetRegionParams(BaseModel):
	"""Query of ``GET /store/regions/{id}``.

	The pinned ``StoreGetRegionParams`` is a bare ``SelectParams`` upstream;
	Ceto serves no ``fields`` selector on the config-backed projection yet,
	so the model accepts nothing and forbids everything: every key —
	including a ``fields`` selector the fixed projection never applies — is
	refused as ``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
