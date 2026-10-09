# Store Reference Data Endpoints — Source of Truth

Phase 1 slice A pinned the machine-readable contract manifests for the
reference-data routes a storefront needs before it can transact — **Regions
list/detail, Currencies list/detail and Locales list** — and implemented the
read-only services behind them. Slice B then completes the pinned surface:
**Phase 1 slice B registers the complete surface** — all five pinned routes,
from `GET /store/regions` through `GET /store/locales` (see
[Implemented routes](#implemented-routes)); the README marks every
reference-data row ✅. The route adapters are the thin
boundary modules `ceto/api/store/regions.py`, `ceto/api/store/currencies.py`
and `ceto/api/store/locales.py`; every read is guest-dispatchable with the
publishable API key as the only credential (the shared scope-less boundary
check of `StorePublishableKey`), validated against the pinned query
contracts before anything resolves, and rendered in the stable Medusa error
shapes (`400 invalid_data`, `404 not_found`, `401 unauthorized`). The
coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_*_manifest`), the API boundary suites
(`ceto.tests.api.store.test_regions`, `test_currencies`, `test_locales`),
the docs↔manifest inventory check
(`ceto.tests.docs.test_reference_data_endpoints`) and the router surface
check in `ceto.tests.routing.test_router`.

## Manifests

| Surface | Module | Tests |
|---|---|---|
| Regions | `ceto/types/http/store/regions/manifest.py` | `ceto/tests/types/http/store/test_regions_manifest.py` |
| Currencies | `ceto/types/http/store/currencies/manifest.py` | `ceto/tests/types/http/store/test_currencies_manifest.py` |
| Locales | `ceto/types/http/store/locales/manifest.py` | `ceto/tests/types/http/store/test_locales_manifest.py` |

- API source (pinned): <https://docs.medusajs.com/api/store> (regions,
  currencies, locales)

All three follow the carts Phase 0 pattern: pure Python (`dataclass` route
entries, no Frappe imports), pinned to the lockstep release the rest of the
repo pins — `@medusajs/js-sdk@2.21.1` and `@medusajs/types@2.21.1` — plus
`@medusajs/medusa@2.21.1` for the server facts the SDK does not carry
(publishable-key middleware, list validator defaults). Each was verified
against the published packages themselves, not documentation alone.

## Pinned routes (5)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | GET | `/store/regions` | — | `StoreRegionListResponse` | `StoreRegionFilters` | publishable-key | `list` |
| 2 | GET | `/store/regions/{id}` | — | `StoreRegionResponse` | `StoreGetRegionParams` | publishable-key | `retrieve` |
| 3 | GET | `/store/currencies` | — | `StoreCurrencyListResponse` | `StoreGetCurrencyListParams` | publishable-key | — |
| 4 | GET | `/store/currencies/{code}` | — | `StoreCurrencyResponse` | `StoreGetCurrencyParams` | publishable-key | — |
| 5 | GET | `/store/locales` | — | `StoreLocaleListResponse` | — | publishable-key | `list` |

- The pinned SDK has **no currency namespace at all**, so routes 3–4 need a
  raw HTTP client when replicating Medusa client behavior (like the cart
  `taxes` route).
- Locales: upstream 2.21.1 ships `GET /store/locales` behind its
  `translation` feature flag, backed by the i18n locale module. Ceto serves
  the route **unconditionally**, backed by its own provisioning — the
  enabled Frappe `Language` records. The route shape stays pinned to
  `@medusajs/types@2.21.1`; the provisioning and the single response
  extension (`default_locale`, optional) are **Ceto-owned** and labeled as
  such on the response model and in
  [field-mapping.md](./field-mapping.md).

## Pagination

The upstream list validators pin the defaults Ceto serves: regions default
to `offset: 0` / `limit: 20`, currencies to `offset: 0` / `limit: 50`. The
locales list is unpaged upstream and stays unpaged in Ceto. One Ceto
decision applies to both paged lists (NOT upstream parity — the pinned
validators bound no page size): a page is capped at 100 rows
(`REGION_LIST_MAX_LIMIT` / `CURRENCY_LIST_MAX_LIMIT`), and the envelope
echoes the effective `offset` / `limit` with the count taken over the whole
servable set before pagination. Ordering is deterministic everywhere:
regions by region id, currencies by lowercase code, locales by code.

## Query behavior

The pinned query contracts live in
`ceto/types/http/store/{regions,currencies,locales}/queries.py` and are
validated at the boundary before any read resolves. Unknown keys are
rejected like on every core payload: out-of-bounds pagination (`limit`
above the manifest bound, negative numbers) and the upstream search (`q`),
combinator (`$and`/`$or`), sort (`order`) and `fields` selector surfaces
are refused as `400 invalid_data` instead of silently ignored or clamped —
the config-backed projections have no searchable column and no selectable
surface beyond the pinned entity, and a client must never receive a page it
cannot reproduce. The detail routes accept no query at all, so every
detail answer is the identical projection the list serves.

## Implemented routes

Phase 1 slice B completes the pinned surface: all five README rows are ✅.

### `GET /store/regions` — `ceto.api.store.regions.list_regions`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the storefront key store and
  never persisted; no customer session exists on reference data.
- The pinned `StoreRegionFilters` validate the page before anything
  resolves; unknown keys and out-of-bounds pagination fail as
  `400 invalid_data`.
- Serves only the configured regions that resolve all three commerce
  anchors (existing Company, selling Price List, currency) — the identical
  resolution rule the cart service applies, shared through
  `ceto.config.cart` — so every served region is cart-valid. Unservable
  regions are invisible to the page, never errors.

### `GET /store/regions/{id}` — `ceto.api.store.regions.retrieve_region`

- Same publishable-key boundary as the list; an unknown or unservable
  region id is the same masked `404 not_found`, never a `500`, so a broken
  region overlay cannot surface.
- The pinned `StoreGetRegionParams` accepts no query yet: every key —
  including a `fields` selector — is refused as `400 invalid_data` before
  the region resolves, so detail always answers with the identical
  projection the list serves.

### `GET /store/currencies` — `ceto.api.store.currencies.list_currencies`

- Same publishable-key boundary; the pinned `StoreGetCurrencyListParams`
  validate the page with the currencies' own bounds (default
  `limit: 50`, cap 100).
- The list is scoped, never the whole ERPNext currency table: only the
  currencies valid configured commerce regions reference are served,
  deduplicated and ordered by lowercase code.

### `GET /store/currencies/{code}` — `ceto.api.store.currencies.retrieve_currency`

- Same publishable-key boundary; the code resolves case-insensitively.
- A currency no valid region references — like an unknown one — is the
  same masked `404 not_found`; every query key is refused as
  `400 invalid_data` before the currency resolves.

### `GET /store/locales` — `ceto.api.store.locales.list_locales`

- Same publishable-key boundary; unlike upstream there is no feature flag —
  Ceto always serves the route on its own provisioning.
- Lists the enabled Frappe `Language` records ordered by code and resolves
  the labeled `default_locale` extension through the documented chain:
  configured `ceto_cart.default_locale` → enabled site language → enabled
  `en` → first enabled code → `None`.
- Upstream pins no query contract for the unpaged route, so the
  strict-empty `StoreLocaleListParams` refuses every key as
  `400 invalid_data`.

## Deliberate omissions

- **No region countries, payment providers or metadata** — see
  [field-mapping.md](./field-mapping.md) for each omission and its reason.
- **No `q` search, `$and`/`$or` combinators, `order` sort expressions or
  `fields` selectors** — the config-backed projections expose no searchable
  column and no selectable surface beyond the pinned entity; every such key
  is rejected as `400 invalid_data` (see [Query behavior](#query-behavior)).
