# Store Reference Data Endpoints — Source of Truth

Phase 1 slice A pins the machine-readable contract manifests for the
reference-data routes a storefront needs before it can transact — **Regions
list/detail, Currencies list/detail and Locales list** — and implements the
read-only services behind them. **No route is registered on the router in
this slice**: the API route adapters (and the README ✅ marks) land with the
next slice, so every README reference-data row stays ⚪️ for now.

## Manifests

| Surface | Module | Tests |
|---|---|---|
| Regions | `ceto/types/http/store/regions/manifest.py` | `ceto/tests/types/http/store/test_regions_manifest.py` |
| Currencies | `ceto/types/http/store/currencies/manifest.py` | `ceto/tests/types/http/store/test_currencies_manifest.py` |
| Locales | `ceto/types/http/store/locales/manifest.py` | `ceto/tests/types/http/store/test_locales_manifest.py` |

All three follow the carts Phase 0 pattern: pure Python (`dataclass` route
entries, no Frappe imports), pinned to the lockstep release the rest of the
repo pins — `@medusajs/js-sdk@2.21.1` and `@medusajs/types@2.21.1` — plus
`@medusajs/medusa@2.21.1` for the server facts the SDK does not carry
(publishable-key middleware, list validator defaults). Each was verified
against the published packages themselves, not documentation alone.

## Pinned routes (5)

| # | Method | Path | Request type | Response type | Auth | SDK method |
|---|--------|------|--------------|---------------|------|------------|
| 1 | GET | `/store/regions` | — | `StoreRegionListResponse` | publishable-key | `list` |
| 2 | GET | `/store/regions/{id}` | — | `StoreRegionResponse` | publishable-key | `retrieve` |
| 3 | GET | `/store/currencies` | — | `StoreCurrencyListResponse` | publishable-key | — |
| 4 | GET | `/store/currencies/{code}` | — | `StoreCurrencyResponse` | publishable-key | — |
| 5 | GET | `/store/locales` | — | `StoreLocaleListResponse` | publishable-key | `list` |

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

## Deliberate omissions in this slice

- **No route adapters** — the five routes are pinned and served by services
  (`ceto/services/reference/`), but nothing is registered on
  `ceto_router` yet, and the README rows stay ⚪️ until that slice.
- **No query/filter contracts** — `StoreRegionFilters`,
  `StoreGetRegionParams`, `StoreGetCurrencyListParams`,
  `StoreGetCurrencyParams` (`q`, `code`, `fields`, sort selectors) are not
  pinned as Pydantic contracts yet; the services accept `limit`/`offset`
  only. The query contracts land together with the route adapters that must
  enforce them.
- **No region countries, payment providers or metadata** — see
  [field-mapping.md](./field-mapping.md) for each omission and its reason.
