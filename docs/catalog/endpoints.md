# Store Catalog Taxonomy Endpoints — Source of Truth

Phase 2 slice 2A pins the machine-readable contract manifests for the catalog
taxonomy reads a storefront needs to browse the published assortment —
**Collections list/detail, Product Categories list/detail, Product Tags
list/detail and Product Types list/detail** — plus their query and response
contracts. **No route of this slice is registered yet**: a behavior slice
registers the eight pinned routes on the router and serves them, and only
then do the README rows flip to ✅ (they deliberately stay ⚪️ now). The
manifests, query models and response envelopes are complete and testable
today; the route adapters, services and storage DocTypes belong to the
behavior slices. The coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_collections_manifest`,
`test_product_categories_manifest`, `test_product_tags_manifest`,
`test_product_types_manifest`), the contract tests beside them, and the
docs↔manifest↔README inventory check
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

Phase 2 slice 2A pins the contract only. No catalog route is registered on
`ceto_router`, no service exists, and no storage DocType ships in this
slice; the README marks all eight routes ⚪️ and the docs drift test fails
if any of them is marked ✅ before a behavior slice implements it.

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
- **No bootstrap fixtures** — demo collections/types are approved with the
  behavior slices that own the storage (Recorded Decision 7).
