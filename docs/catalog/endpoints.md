# Store Catalog Taxonomy Endpoints — Source of Truth

Phase 2 slice 2A pinned the machine-readable contract manifests for the catalog
taxonomy reads a storefront needs to browse the published assortment —
**Collections list/detail, Product Categories list/detail, Product Tags
list/detail and Product Types list/detail** — plus their query and response
contracts. **Phase 2 slices 2B, 2C and 2D register the served halves**: slice 2B
serves the collections and product types from Ceto-owned storage DocTypes,
slice 2C serves the category pair as an `Item Group`-tree projection inside
the configured storefront roots, and slice 2D serves the tag pair as a
projection of the live Frappe tag masters and their exact `Item` Tag Link rows
(see [Implemented routes](#implemented-routes)); the README marks exactly those
eight rows ✅. The coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_collections_manifest`,
`test_product_categories_manifest`,
`test_product_tags_manifest`,
`test_product_types_manifest`), the contract tests beside them, the API
boundary suites for the served halves (`ceto.tests.api.store.test_collections`,
`test_product_categories`, `test_product_tags`, `test_product_types`), the router surface check in
`ceto.tests.routing.test_router`, and the docs↔manifest↔README inventory check
(`ceto.tests.docs.test_catalog_endpoints`).

## Manifests

| Surface | Module | Tests |
|---|---|---|
| Collections | `ceto/types/http/store/collections/manifest.py` | `ceto/tests/types/http/store/test_collections_manifest.py` |
| Product Categories | `ceto/types/http/store/product_categories/manifest.py` | `ceto/tests/types/http/store/test_product_categories_manifest.py` |
| Product Tags | `ceto/types/http/store/product_tags/manifest.py` | `ceto/tests/types/http/store/test_product_tags_manifest.py` |
| Product Types | `ceto/types/http/store/product_types/manifest.py` | `ceto/tests/types/http/store/test_product_types_manifest.py` |

- API source (pinned): <https://docs.medusajs.com/api/store> (collections,
  product-categories, product-tags, product-types)

All four follow the reference-data Phase 1 pattern: pure Python
(`dataclass` route entries, no Frappe imports), pinned to the lockstep
release the rest of the repo pins — `@medusajs/js-sdk@2.21.1` and
`@medusajs/types@2.21.1` — plus `@medusajs/medusa@2.21.1` for the server
facts the SDK does not carry (publishable-key middleware, list validator
defaults). Each was verified against the published packages themselves, not
documentation alone.

## Pinned routes (8)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | GET | `/store/collections` | — | `StoreCollectionListResponse` | `StoreCollectionListParams` | publishable-key | `list` |
| 2 | GET | `/store/collections/{id}` | — | `StoreCollectionResponse` | `StoreCollectionParams` | publishable-key | `retrieve` |
| 3 | GET | `/store/product-categories` | — | `StoreProductCategoryListResponse` | `StoreProductCategoryListParams` | publishable-key | `list` |
| 4 | GET | `/store/product-categories/{id}` | — | `StoreProductCategoryResponse` | `StoreProductCategoryParams` | publishable-key | `retrieve` |
| 5 | GET | `/store/product-tags` | — | `StoreProductTagListResponse` | `StoreProductTagListParams` | publishable-key | — |
| 6 | GET | `/store/product-tags/{id}` | — | `StoreProductTagResponse` | `StoreProductTagParams` | publishable-key | — |
| 7 | GET | `/store/product-types` | — | `StoreProductTypeListResponse` | `StoreProductTypeListParams` | publishable-key | — |
| 8 | GET | `/store/product-types/{id}` | — | `StoreProductTypeResponse` | `StoreProductTypeParams` | publishable-key | — |

- Routes 1–2 are covered by the `sdk.store.collection` namespace and routes
  3–4 by the `sdk.store.category` namespace of the pinned SDK — note the
  category namespace is named `category`, not `productCategory`.
- The pinned SDK has **no product-tag and no product-type namespace at
  all**, so routes 5–8 need a raw HTTP client when replicating Medusa
  client behavior (like the currency routes).

## Auth and error semantics

Every pinned route is a guest-dispatchable Store read with the publishable
API key as the only credential — the identical boundary reference data
uses (the `x-publishable-api-key` header, validated at the boundary and
never persisted; no customer session exists on catalog reads). The error
contract is the stable Medusa set:

- `401 unauthorized` — missing or unknown publishable key.
- `400 invalid_data` — every rejected query key (see
  [Query behavior](#query-behavior)) and every out-of-bounds pagination
  number; nothing is silently ignored or clamped.
- `404 not_found` — an unknown id, and an unpublished one: outside the
  configured storefront roots a category does not exist, it masks as `404`
  exactly like an unservable reference record, never a `500`.

## Storefront roots configuration

The served taxonomy is a deployment decision (Recorded Decision 1): the
storefront root `Item Group` nodes live in the `ceto_catalog.category_roots`
site configuration, parsed once through `ceto.config.catalog` — the same
one-config-shape, one-parser rule `ceto.config.cart` applies to the cart
keys. The value is one root name or a list of names; blank and non-string
entries are dropped and duplicates collapse, never an error:

```json
{
  "ceto_catalog": {
    "category_roots": ["Apparel", "Footwear"]
  }
}
```

- A category is served exactly when its `Item Group` node is a configured
  root or descends from one; nothing outside the roots — the `All Item
  Groups` default tree included — is ever listed, and an unknown or
  unpublished id masks as `404 not_found`.
- The parser never validates that a configured root exists: an unknown root
  publishes nothing instead of failing the read, the same masked rule the
  region anchors apply.
- **Backward-safe default:** with no `ceto_catalog` configuration (or an
  unusable value) the directory publishes nothing — the list answers an
  empty page and every detail masks as `404`. The routes never fall back to
  the ERPNext default tree.
- The configuration is read per request and never persisted anywhere.

## Pagination

The upstream list validators pin the defaults Ceto serves: collections
default to `offset: 0` / `limit: 10` (with the upstream default sort
`-created_at`), product categories, product tags and product types to
`offset: 0` / `limit: 50`. One Ceto decision applies to all four paged
lists (NOT upstream parity — the pinned validators bound no page size): a
page is capped at 100 rows (`*_LIST_MAX_LIMIT` per manifest), and the
envelope echoes the effective `offset` / `limit` with the count taken over
the whole servable set before pagination.

## Ordering

Deterministic everywhere (Recorded Decision 6):

- Collections by creation descending — matching the upstream validator's
  pinned default sort `-created_at`; the record id breaks ties.
- Product categories by `lft` — the ERPNext `Item Group` tree order, so a
  plain page reads as a stable pre-order walk of the published taxonomy.
- Product tags and product types by `value` ascending.

## Query behavior

The pinned query contracts live in
`ceto/types/http/store/{collections,product_categories,product_tags,product_types}/queries.py`
and are validated at the boundary before any read resolves. Unknown keys
are rejected like on every core payload: out-of-bounds pagination
(`limit` above the manifest bound, negative numbers) and the upstream
search (`q`), filter (`id`, `title`, `handle`, `value`, `name`,
`parent_category_id`, `external_id`, …), operator-map
(`created_at`/`updated_at`), combinator (`$and`/`$or`), sort (`order`) and
`fields` selector surfaces are refused as `400 invalid_data` instead of
silently ignored or clamped — the projections have no searchable column
and no selectable surface beyond the pinned entity, and a client must
never receive a page it cannot reproduce. The detail routes accept no
query at all, so every detail answer is the identical projection the list
serves.

The category tree expansion flags are deliberately unsupported (Recorded
Decision 5): `include_descendants_tree` / `include_ancestors_tree` are
refused as unknown keys on the list and the detail route until the tree
population decision lands.

## Implementation status

Phase 2 slice 2A pinned the contract; slices 2B, 2C and 2D implement the whole
pinned inventory. The collections and product types reads are served from the
Ceto-owned `Ceto Collection` / `Ceto Product Type` storage DocTypes through
the `ceto.services.catalog` directories — unique stored handles and curated
values, minted `pcol_…` / `ptyp_…` public ids, optional `external_id` and
canonical JSON `metadata` columns, and real record timestamps served as-is
(Recorded Decision 8) — with the demo fixtures seeded by the bootstrap
(`ceto.data.bootstrap_dev.seeders.setup_catalog`, Recorded Decision 7).

Slice 2C serves the category pair from the ERPNext `Item Group` tree through
`ProductCategoryDirectory`: only the configured storefront roots
(`ceto_catalog.category_roots`, see
[Storefront roots configuration](#storefront-roots-configuration)) and their
NestedSet descendants are published, the page is the tree's own `lft`
pre-order walk (Recorded Decision 6) with the count taken over the whole
published set before pagination, the public `pcat_…` id is derived
deterministically from the node name (no core schema change), the handle is
the slug of `item_group_name`, the timestamps are the real record
`creation` / `modified` (Recorded Decision 8), and the projection stays flat
(Recorded Decision 5).

Slice 2D serves the tag pair from the live Frappe tag masters through
`ProductTagDirectory`: a tag serves exactly while its `Tag` master is live
and at least one of its exact `Tag Link` rows names an `Item` that still
exists — orphan links, links to deleted Items and masters without any live
link never surface. The page is the value-ascending order of the distinct
served values (Recorded Decision 6) with the count taken over the whole
served set before pagination, the public `ptag_…` id is derived
deterministically from the tag value (no core schema change), and the tag
serves no timestamps of its own (Recorded Decision 8). The demo tags ship
with the behavior slice, seeded by the bootstrap's `SetupItemTags` step
(Recorded Decision 7).

## Implemented routes

Phase 2 slices 2B, 2C and 2D register exactly these eight routes; the whole
pinned taxonomy inventory is served.

### `GET /store/collections` — `ceto.api.store.collections.list_collections`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the storefront key store and
  never persisted; no customer session exists on catalog reads.
- The pinned `StoreCollectionListParams` validate the page before anything
  resolves: the upstream `q` search, `id`/`title`/`handle`/`external_id`
  filters, operator maps, `$and`/`$or`, `order` and `fields` keys and
  out-of-bounds pagination all fail as `400 invalid_data`.
- Pages the stored collections creation-descending — the upstream pinned
  default sort — with the record id breaking ties, and echoes the effective
  `offset` / `limit` with the count taken over the whole stored set before
  pagination.

### `GET /store/collections/{id}` — `ceto.api.store.collections.retrieve_collection`

- Same publishable-key boundary; an unknown id is the masked `404
  not_found`, never a `500`.
- The pinned `StoreCollectionParams` accepts no query at all: every key —
  including a `fields` selector — is refused as `400 invalid_data` before
  the collection resolves, so detail always answers with the identical
  projection the list serves.

### `GET /store/product-categories` — `ceto.api.store.product_categories.list_product_categories`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the storefront key store and
  never persisted; no customer session exists on catalog reads.
- The pinned `StoreProductCategoryListParams` validate the page before
  anything resolves: the upstream `q` search, `id`/`name`/`handle`/
  `parent_category_id`/`external_id`/`is_active`/`is_internal` filters,
  operator maps, `$and`/`$or`, `order` and `fields` keys, the
  `include_descendants_tree` / `include_ancestors_tree` tree flags
  (Recorded Decision 5) and out-of-bounds pagination all fail as `400
  invalid_data`.
- Serves only the configured storefront roots and their NestedSet
  descendants, ordered by `lft` — the tree's own pre-order walk (Recorded
  Decision 6) — and echoes the effective `offset` / `limit` with the count
  taken over the whole published set before pagination.

### `GET /store/product-categories/{id}` — `ceto.api.store.product_categories.retrieve_product_category`

- Same publishable-key boundary; an unknown id — and an `Item Group`
  outside the configured storefront roots, which does not exist on the
  Store surface — is the same masked `404 not_found`, never a `500`.
- The pinned `StoreProductCategoryParams` accepts no query at all: every
  key — including a `fields` selector or a tree expansion flag — is refused
  as `400 invalid_data` before the category resolves, so detail always
  answers with the identical projection the list serves.

### `GET /store/product-tags` — `ceto.api.store.product_tags.list_product_tags`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the storefront key store and
  never persisted; no customer session exists on catalog reads.
- The pinned `StoreProductTagListParams` validate the page before anything
  resolves: the upstream `q` search, `id`/`value`/`external_id` filters,
  operator maps, `$and`/`$or`, `order` and `fields` keys and out-of-bounds
  pagination all fail as `400 invalid_data`.
- Pages the distinct served tag values value-ascending (Recorded Decision 6)
  and echoes the effective `offset` / `limit` with the count taken over the
  whole served set before pagination. A tag serves exactly while its `Tag`
  master is live and one of its exact `Tag Link` rows names an `Item` that
  still exists; a tag serves no timestamps of its own (Recorded Decision 8).

### `GET /store/product-tags/{id}` — `ceto.api.store.product_tags.retrieve_product_tag`

- Same publishable-key boundary; an unknown id is the masked `404
  not_found`, never a `500`.
- The public `ptag_…` id is derived deterministically from the tag value
  (SHA-256 truncation, no core schema change), so a served tag keeps its id
  for its whole lifetime without minted storage.
- The pinned `StoreProductTagParams` accepts no query at all: every key —
  including a `fields` selector — is refused as `400 invalid_data` before
  the tag resolves, so detail always answers with the identical projection
  the list serves.

### `GET /store/product-types` — `ceto.api.store.product_types.list_product_types`

- Same publishable-key boundary and strict query validation as the
  collections list, against the pinned `StoreProductTypeListParams`.
- Pages the stored curated types value-ascending (Recorded Decision 6) with
  the record id breaking ties, and echoes the effective `offset` / `limit`
  with the count taken over the whole stored set before pagination.

### `GET /store/product-types/{id}` — `ceto.api.store.product_types.retrieve_product_type`

- Same publishable-key boundary; an unknown id is the masked `404
  not_found`, never a `500`.
- The pinned `StoreProductTypeParams` accepts no query at all: every key is
  refused as `400 invalid_data` before the type resolves, so detail always
  answers with the identical projection the list serves.

## Deliberate omissions

- **No collection `products` relation** — collection-item membership is
  deferred (Recorded Decision 4,
  [field-mapping.md](./field-mapping.md)).
- **No category tree expansion** — the flat projection ships first;
  `parent_category` / `category_children` default to the empty tree and
  the tree flags are rejected (Recorded Decision 5).
- **No `q` search, filters, operator maps, `$and`/`$or` combinators,
  `order` sort expressions or `fields` selectors** — the projections
  expose no searchable column and no selectable surface beyond the pinned
  entity; every such key is rejected as `400 invalid_data` (see
  [Query behavior](#query-behavior)).

The demo collections and types ship with slice 2B, seeded by the
development bootstrap's `SetupCatalog` step (Recorded Decision 7); the demo
`Item Group` overlays ship with slice 2C — `Dev Graphic Tees` extends the
`Dev *` tree to a third level under `Dev Apparel > Dev T-Shirts`, seeded by
`SetupItemGroups` and served once the deployment names its storefront roots
in `ceto_catalog.category_roots` (see the bootstrap README for the demo
snippet). The demo tags ship with slice 2D — `Dev New Arrival`, `Dev Summer`
and `Dev Footwear` are pinned on the demo `DEV-*` items by `SetupItemTags`,
and serve immediately: the tag projection needs no site configuration.
