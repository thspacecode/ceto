# Store Product Endpoints — Source of Truth

Phase 3 pins the machine-readable contract manifests for the product reads
a storefront needs to merchandise the published assortment — **Products
list/detail, Product Variants list and Product Options list/detail** — plus
their query and response contracts (`ceto/types/http/store/products`). The
slice is contract-only: **no route is registered on the router, no API
module ships and every README row for the five routes stays ⚪️** until the
products behavior slice lands. The coverage guard is the manifest drift
tests (`ceto.tests.types.http.store.test_products_manifest`), the contract
tests beside them (`test_products_entities`, `test_products_queries`) and
the docs↔manifest↔README inventory check
(`ceto.tests.docs.test_products_endpoints`), which also fails if a README
product row flips to ✅ before the behavior slice registers the route.

## Manifest

| Surface | Module | Tests |
|---|---|---|
| Products, Variants, Options | `ceto/types/http/store/products/manifest.py` | `ceto/tests/types/http/store/test_products_manifest.py` |

- API sources (pinned): <https://docs.medusajs.com/api/store/products>,
  <https://docs.medusajs.com/api/store/product-variants>,
  <https://docs.medusajs.com/api/store/product-options>

The manifest follows the Phase 1/2 pattern: pure Python (`dataclass` route
entries, no Frappe imports), pinned to the lockstep release the rest of the
repo pins — `@medusajs/js-sdk@2.21.1` and `@medusajs/types@2.21.1` — plus
`@medusajs/medusa@2.21.1` for the server facts the SDK does not carry
(publishable-key boundary, `status: published` default filter, list
validator defaults). Everything below was verified against the published
packages themselves, not documentation alone.

## Pinned routes (5)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | GET | `/store/products` | — | `StoreProductListResponse` | `StoreProductListParams` | publishable-key | `list` |
| 2 | GET | `/store/products/{id}` | — | `StoreProductResponse` | `StoreProductParams` | publishable-key | `retrieve` |
| 3 | GET | `/store/product-variants` | — | `StoreProductVariantListResponse` | `StoreProductVariantListParams` | publishable-key | — |
| 4 | GET | `/store/product-options` | — | `StoreProductOptionListResponse` | `StoreProductOptionListParams` | publishable-key | `list` |
| 5 | GET | `/store/product-options/{id}` | — | `StoreProductOptionResponse` | `StoreProductOptionParams` | publishable-key | `retrieve` |

- Routes 1–2 are covered by the `sdk.store.product` namespace and routes
  4–5 by the `sdk.store.productOption` namespace of the pinned SDK — note
  the option namespace is camelCase `productOption` (shipped in 2.16.0).
- The pinned SDK has **no product-variant namespace at all** (it makes no
  `/store/product-variants` call anywhere), so route 3 needs a raw HTTP
  client when replicating Medusa client behavior (like the currency and
  locale routes).
- The upstream server also serves `GET /store/product-variants/{id}`
  (since 2.11.2); it is deliberately out of the pinned inventory — the
  list is the canonical variants surface (products slice decision 5 in
  [products-field-mapping.md](./products-field-mapping.md)) and the README
  inventory lists only the list route.

## Auth and error semantics

Every pinned route is a guest-dispatchable Store read with the publishable
API key as the only credential — the identical boundary the taxonomy reads
use (the `x-publishable-api-key` header, validated at the boundary and
never persisted; no customer session exists on catalog reads). The error
contract is the stable Medusa set:

- `401 unauthorized` — missing or unknown publishable key.
- `400 invalid_data` — every rejected query key (see
  [Query behavior](#query-behavior)) and every out-of-bounds pagination
  number; nothing is silently ignored or clamped.
- `404 not_found` — an unknown id, and an unpublished one: a product
  outside the configured storefront roots does not exist on the Store
  surface, it masks as `404` exactly like an unservable taxonomy record,
  never a `500`.

## Pagination

The upstream list validators pin the defaults Ceto serves: products and
product options default to `offset: 0` / `limit: 50`, product variants to
`offset: 0` / `limit: 20`. One Ceto decision applies to all three paged
lists (NOT upstream parity — the pinned validators bound no page size): a
page is capped at 100 rows (`*_LIST_MAX_LIMIT` per manifest), and the
envelope echoes the effective `offset` / `limit` with the count taken over
the whole servable set before pagination.

## Ordering

Deterministic everywhere (the taxonomy Recorded Decision 6 convention) —
the exact per-surface order is a behavior-slice decision; upstream pins no
default sort on these three routes.

## Query behavior

The pinned query contracts live in
`ceto/types/http/store/products/queries.py` and are validated at the
boundary before any read resolves. Unknown keys are rejected like on every
core payload: out-of-bounds pagination (`limit` above the manifest bound,
negative numbers) and the upstream `q` search, filter (`id`, `title`,
`handle`, `sku`, `product_id`, `collection_id`, `type_id`, `tag_id`,
`category_id`, `external_id`, `is_giftcard`, `status`, `sales_channel_id`,
`options`, `is_exclusive`, …), operator-map
(`created_at`/`updated_at`/`deleted_at`), combinator (`$and`/`$or`), sort
(`order`), `fields` selector, nested `variants` filter and `locale`
surfaces are refused as `400 invalid_data` instead of silently ignored or
clamped — the projections expose no searchable column and no selectable
surface beyond the pinned entities.

The pricing-context keys are refused deliberately (products slice decision
6): `region_id`, `country_code`, `province` and `cart_id` drive upstream's
variant price calculation, and cart publication enforcement is out of
scope until the pricing slice decides it. The detail routes accept no
query at all, so every detail answer is the identical projection the list
serves.

## Implementation status

Phase 3 pins the contract; the behavior slice registers the five routes on
the router and serves the published assortment from the configured
storefront roots (products slice decision 1). Until that slice lands:

- no route handler exists under `ceto.api.store` for the five paths;
- the router surface is unchanged (`ceto.tests.routing.test_router` keeps
  passing untouched);
- the README rows for `/store/products`, `/store/products/{id}`,
  `/store/product-variants`, `/store/product-options` and
  `/store/product-options/{id}` stay ⚪️ (guarded by
  `ceto.tests.docs.test_products_endpoints`).

## Deliberate omissions

- **No variants detail route** — the canonical variants surface is the
  list (decision 5); the upstream detail route stays out of the pinned
  inventory.
- **No `calculated_price` / `inventory_quantity` columns** — pricing and
  inventory are behavior-slice decisions; the projection models drop both
  entirely instead of stubbing them.
- **No collection/type link population** — the Ceto-owned links land with
  the behavior slice (decision 4); `collection_id`, `collection`, `type_id`
  and `type` stay optional and unpopulated.
- **No `q` search, filters, operator maps, `$and`/`$or` combinators,
  `order` sort expressions, `fields` selectors, `locale` or pricing
  context** — every such key is rejected as `400 invalid_data` (see
  [Query behavior](#query-behavior)).
