# Store Product Endpoints — Source of Truth

Phase 3 pinned the machine-readable contract manifests for the product reads
a storefront needs to merchandise the published assortment — **Products
list/detail, Product Variants list and Product Options list/detail** — plus
their query and response contracts (`ceto/types/http/store/products`), the
served projection behind them — the family assembly
(`ceto/services/catalog/families.py`), the batched serializer
(`ceto/services/catalog/products.py`) and the region-aware pricing authority
(`ceto/services/catalog/pricing.py`) — and registered the complete surface:
all five pinned routes, from `GET /store/products` through
`GET /store/product-options/{id}` (see
[Implemented routes](#implemented-routes)); the README marks every product
row ✅. The route adapter is the thin boundary module
`ceto/api/store/products.py`; every read is guest-dispatchable with the
publishable API key as the only credential (the shared scope-less boundary
check of `StorePublishableKey`, the handler's first statement), validated
against the pinned query contracts before anything resolves, and rendered in
the stable Medusa error shapes (`400 invalid_data`, `404 not_found`,
`401 unauthorized`). The coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_products_manifest`), the contract tests
beside them (`test_products_entities`, `test_products_queries`), the
service suites over the published assortment
(`ceto.tests.services.catalog.test_families`, `test_pricing`,
`test_products`), the API boundary suite
(`ceto.tests.api.store.test_products`), the router surface check in
`ceto.tests.routing.test_router` and the docs↔manifest↔README inventory
check (`ceto.tests.docs.test_products_endpoints`).

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
use (the `x-publishable-api-key` header, validated at the boundary against
the storefront key store and never persisted; no customer session exists on
catalog reads). Each handler runs the boundary check before it validates or
resolves anything, so the surface answers identically whether or not a
customer session exists. The error contract is the stable Medusa set:

- `401 unauthorized` — missing or unknown publishable key.
- `400 invalid_data` — every rejected query key (see
  [Query behavior](#query-behavior)), every out-of-bounds pagination
  number and a pricing context that fails the cart resolution; nothing is
  silently ignored or clamped.
- `404 not_found` — an unknown, malformed or unpublished id: a product
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

Deterministic everywhere (the taxonomy Recorded Decision 6 convention):
products order by item title then item code, the variants surface by item
code, options by title then id and option values value-ascending — upstream
pins no default sort on these three routes.

## Query behavior

The pinned query contracts live in
`ceto/types/http/store/products/queries.py` and are validated at the
boundary before any read resolves. The accepted members are exactly the
pinned ones — pagination (`limit`, `offset`) on the three lists and the
pricing context `region_id` on the priced surfaces; the option detail route
accepts no query at all. Everything else is rejected like on every core
payload: out-of-bounds pagination (`limit` above the manifest bound,
negative numbers, non-integers) and the upstream `q` search, filter (`id`,
`title`, `handle`, `sku`, `product_id`, `collection_id`, `type_id`,
`tag_id`, `category_id`, `external_id`, `is_giftcard`, `status`,
`sales_channel_id`, `options`, `is_exclusive`, …), operator-map
(`created_at`/`updated_at`/`deleted_at`), combinator (`$and`/`$or`), sort
(`order`), `fields` selector, nested `variants` filter and `locale`
surfaces are refused as `400 invalid_data` instead of silently ignored or
clamped — the projections expose no searchable column and no selectable
surface beyond the pinned entities.

The pricing context is the one accepted exception (products slice decision
6): `region_id` is accepted on the priced surfaces — the products list, the
product detail and the variants list — and resolves through the cart
price-list authority into the served `calculated_price`; a blank or absent
value serves the projection unpriced instead of guessing a default, and a
value that fails the cart resolution raises the cart configuration's own
`invalid_data` error. The remaining upstream pricing-context keys —
`country_code`, `province` and `cart_id` — stay refused as unknown fields,
and the option routes accept no pricing context at all.

## Implemented routes

The products slice registers exactly these five routes; the whole pinned
product inventory is served.

### `GET /store/products` — `ceto.api.store.products.list_products`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the storefront key store and
  never persisted; no customer session exists on catalog reads — the
  boundary check is the handler's first statement, before the query
  validates.
- The pinned `StoreProductListParams` validate the page before anything
  resolves. The accepted members are exactly `limit` (default `50`,
  `0`–`100`), `offset` (default `0`, non-negative) and `region_id`; the
  upstream search, filter, operator-map, combinator, sort, `fields`,
  `locale` and nested `variants` surfaces, the other pricing-context keys
  and every out-of-bounds pagination number fail as `400 invalid_data`.
- Pages the published assortment item-title-then-item-code ordered and
  echoes the effective `offset` / `limit` with the count taken over the
  whole served assortment before pagination.
- A non-empty `region_id` resolves through the cart price-list authority
  and prices the page's variants; an absent or blank value serves the page
  unpriced; a value that fails the cart resolution is the same
  `400 invalid_data` a cart create receives.

### `GET /store/products/{id}` — `ceto.api.store.products.retrieve_product`

- Same publishable-key boundary as the list; an unknown, malformed or
  unpublished id — an `Item` outside the configured storefront roots does
  not exist on the Store surface — is the same masked `404 not_found`,
  never a `500`.
- The pinned `StoreProductParams` accepts exactly one member, the pricing
  context `region_id`: it prices the detail's variants exactly like the
  list's. Every other key — a `fields` selector, `country_code`,
  `province`, `cart_id` — is refused as `400 invalid_data` before the
  product resolves, so detail always answers with the identical projection
  the list serves.

### `GET /store/product-variants` — `ceto.api.store.products.list_product_variants`

- Same publishable-key boundary and strict validation as the products list,
  against the pinned `StoreProductVariantListParams`: the accepted members
  are exactly `limit` (default `20`, `0`–`100`), `offset` (default `0`,
  non-negative) and `region_id`.
- Serves every sellable unit of the published assortment — a family's
  published variants and the standalone items' own variants — in item-code
  order, echoing the effective `offset` / `limit` with the count taken over
  the whole surface before pagination.

### `GET /store/product-options` — `ceto.api.store.products.list_product_options`

- Same publishable-key boundary; the pinned `StoreProductOptionListParams`
  validate the page with exactly `limit` (default `50`, `0`–`100`) and
  `offset` (default `0`, non-negative) — no pricing context exists on the
  option surface.
- Serves every family option of the published assortment — a standalone
  item carries none — title-then-id ordered, echoing the effective
  `offset` / `limit` with the count taken over the whole servable set
  before pagination.

### `GET /store/product-options/{id}` — `ceto.api.store.products.retrieve_product_option`

- Same publishable-key boundary as the list; an unknown, malformed or
  unpublished option id is the same masked `404 not_found`, never a `500`.
- The pinned `StoreProductOptionParams` accepts no query at all: every key
  — including a `fields` selector the fixed projection never applies or
  any pricing context — is refused as `400 invalid_data` before the option
  resolves, so detail always answers with the identical projection the
  list serves.

## Deliberate omissions

- **No variants detail route** — the canonical variants surface is the
  list (decision 5); the upstream detail route stays deliberately out of
  the pinned inventory.
- **No `inventory_quantity` column** — inventory is out of scope; the
  projection model drops it entirely instead of stubbing it.
  `calculated_price`, by contrast, is served: a `StoreCalculatedPrice`
  resolved through the cart price-list authority when the caller presents
  `region_id`, absent otherwise — never a fabricated zero.
- **No collection/type stubbing** — `collection_id`, `collection`,
  `type_id` and `type` serve the `Ceto Product Merchandising` link's
  stored projections verbatim (decision 4); an unlinked product serves all
  four as `None`.
- **No `q` search, filters, operator maps, `$and`/`$or` combinators,
  `order` sort expressions, `fields` selectors or `locale`** — every such
  key is rejected as `400 invalid_data` (see
  [Query behavior](#query-behavior)); the pricing context is exactly the
  accepted `region_id` on the priced surfaces.
