"""Pinned query contracts of the Medusa Store Product Category routes.

Mirrors the pinned query types of ``@medusajs/types@2.21.1``:
``StoreProductCategoryListParams`` carries the ``FindParams`` pagination the
upstream list validator pins (``offset: 0`` / ``limit: 50``, recorded in
the manifest beside the Ceto read-model page bound
``PRODUCT_CATEGORY_LIST_MAX_LIMIT``) and ``StoreProductCategoryParams`` is
a bare ``SelectParams``.

The Ceto read-model bounds one page (``limit`` capped at the manifest
bound, both numbers non-negative), so a request outside the bounds is
rejected as ``400 invalid_data`` instead of silently clamped. The upstream
``q`` search, the ``id``/``name``/``description``/``handle``/
``parent_category_id``/``external_id`` filters, the ``created_at``/
``updated_at`` operator maps, the ``$and``/``$or`` combinators, the
``order`` sort expression and the ``fields`` selector are deliberately
absent and rejected as unknown fields (``docs/catalog/endpoints.md``).

The tree expansion flags stay unsupported on both models (Recorded
Decision 5): ``include_descendants_tree`` and ``include_ancestors_tree``
are refused as unknown keys — the served projection is flat until the
tree population decision lands, so a client must never receive a page it
cannot reproduce.
"""

from pydantic import BaseModel, ConfigDict, Field

from ceto.types.http.store.product_categories.manifest import (
	PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT,
	PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET,
	PRODUCT_CATEGORY_LIST_MAX_LIMIT,
)


class StoreProductCategoryListParams(BaseModel):
	"""Query of ``GET /store/product-categories``.

	Mirrors the pinned ``StoreProductCategoryListParams`` of
	``@medusajs/types@2.21.1`` with the ``FindParams`` pagination. Unknown
	keys are rejected like on every core payload, and the pagination carries
	the Ceto read-model bounds: ``limit`` is the pinned default capped at one
	page's bulk load, ``offset`` non-negative.
	"""

	model_config = ConfigDict(extra="forbid")

	limit: int = Field(default=PRODUCT_CATEGORY_LIST_DEFAULT_LIMIT, ge=0, le=PRODUCT_CATEGORY_LIST_MAX_LIMIT)
	offset: int = Field(default=PRODUCT_CATEGORY_LIST_DEFAULT_OFFSET, ge=0)


class StoreProductCategoryParams(BaseModel):
	"""Query of ``GET /store/product-categories/{id}``.

	The pinned ``StoreProductCategoryParams`` is a bare ``SelectParams``
	upstream plus the two tree expansion flags; Ceto serves no ``fields``
	selector and no tree expansion on the fixed flat projection yet, so the
	model accepts nothing and forbids everything: every key — including a
	``fields`` selector or the ``include_ancestors_tree`` /
	``include_descendants_tree`` flags the fixed projection never applies —
	is refused as ``400 invalid_data`` like every unknown parameter.
	"""

	model_config = ConfigDict(extra="forbid")
