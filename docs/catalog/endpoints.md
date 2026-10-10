# Store Catalog Taxonomy Endpoints — Source of Truth

Phase 2 slice 2A pinned the machine-readable contract manifests for the catalog
taxonomy reads a storefront needs to browse the published assortment —
**Collections list/detail, Product Categories list/detail, Product Tags
list/detail and Product Types list/detail** — plus their query and response
contracts, and **Phase 2 slice 2B registers the Ceto-stored halves**: the
collections and product types list/detail pairs are served from Ceto-owned
storage DocTypes (see [Implemented routes](#implemented-routes)) and the
README marks exactly those four rows ✅. The category and tag manifests stay
contract-only until their behavior slices — an `Item Group`-tree projection
and a user-tag projection respectively — so their four README rows deliberately
stay ⚪️. The coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_collections_manifest`,
`test_product_categories_manifest`, `test_product_tags_manifest`,
`test_product_types_manifest`), the contract tests beside them, the API
boundary suites for the served halves (`ceto.tests.api.store.test_collections`,
`test_product_types`), the router surface check in
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
- `404 not_found` — an unknown id, and (once served) an unpublished one:
  outside the configured storefront roots a category does not exist, it
  masks as `404` exactly like an unservable reference record, never a
  `500`.

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

Phase 2 slice 2A pinned the contract; slice 2B implements the Ceto-stored
halves of it. The collections and product types reads are served from the
Ceto-owned `Ceto Collection` / `Ceto Product Type` storage DocTypes through
the `ceto.services.catalog` directories — unique stored handles and curated
values, minted `pcol_…` / `ptyp_…` public ids, optional `external_id` and
canonical JSON `metadata` columns, and real record timestamps served as-is
(Recorded Decision 8) — with the demo fixtures seeded by the bootstrap
(`ceto.data.bootstrap_dev.seeders.setup_catalog`, Recorded Decision 7). The
product category and product tag routes remain contract-only: no category or
tag route is registered on `ceto_router`, no service or storage exists for
them, and the README marks their four rows ⚪️ until their behavior slices
land.

## Implemented routes

Phase 2 slice 2B registers exactly the four Ceto-stored routes; the category
and tag pairs are inventoried as pinned, not served.

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

- **No category or tag route is served** — those two pairs stay pinned and
  unregistered until their behavior slices (categories project the ERPNext
  `Item Group` tree inside the configured storefront roots, tags project the
  published items' user tags).
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

The demo collections and types ship with this slice, seeded by the
development bootstrap's `SetupCatalog` step (Recorded Decision 7); the demo
`Item Group` overlays for the category slice are approved with that slice.
