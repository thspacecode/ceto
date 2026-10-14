# Store Shipping Option Endpoints — Source of Truth

Phase 4 pinned the machine-readable contract manifest for the shipping-option
reads a storefront needs to offer checkout rates — **`GET /store/shipping-options`
(list a cart's options) and `POST /store/shipping-options/{id}/calculate`
(calculate one option's price on one cart)** — plus their query, payload,
entity and response contracts (`ceto/types/http/store/shipping_options`),
built the provider core behind them — the reversible option-id codec
(`ceto/services/shipping/ids.py`), the frozen quote context
(`ceto/services/shipping/context.py`), the deterministic provider registry
(`ceto/services/shipping/registry.py`) and the built-in ERPNext rules
provider (`ceto/services/shipping/providers/`) — and registered the complete
surface (see [Implemented routes](#implemented-routes)); the README marks
both rows ✅. The route adapter is the thin boundary module
`ceto/api/store/shipping_options.py` and the orchestrating service is
`ceto/services/shipping/service.py`. Every route is guest-dispatchable with
the publishable API key as the only credential, scoped to the resolved cart
through the same guard seam the cart mutations use, validated against the
pinned contracts before anything resolves, and rendered in the stable Medusa
error shapes (`401 unauthorized`, `403 not_allowed`, `400 invalid_data`,
`404 not_found`). The coverage guard is the manifest drift tests
(`ceto.tests.types.http.store.test_shipping_options_manifest`), the contract
tests beside them (`test_shipping_options_entities`,
`test_shipping_options_payloads`, `test_shipping_options_queries`,
`test_shipping_options_responses`), the provider-core suites
(`ceto.tests.services.shipping.test_option_ids`, `test_provider_registry`,
`test_erpnext_adapter`, `test_erpnext_provider`), the service suite
(`ceto.tests.services.shipping.test_store_options`), the apply-seam suites
(`ceto.tests.services.carts.test_shipping`,
`test_shipping_option_ids`), the API boundary suites
(`ceto.tests.api.store.test_shipping_options`,
`test_shipping_options_cart_roundtrip`, `test_carts_shipping_methods`), the
router surface check in `ceto.tests.routing.test_router` and the
docs↔manifest↔README inventory check
(`ceto.tests.docs.test_shipping_options_endpoints`).

## Manifest

| Surface | Module | Tests |
|---|---|---|
| Shipping Options | `ceto/types/http/store/shipping_options/manifest.py` | `ceto/tests/types/http/store/test_shipping_options_manifest.py` |

- API source (pinned): <https://docs.medusajs.com/api/store/shipping-options>
  (list-shipping-options-for-cart and calculate-shipping-option-price)

The manifest follows the Phase 1–3 pattern: pure Python (`dataclass` route
entries, no Frappe imports), pinned to the lockstep release the rest of the
repo pins — `@medusajs/js-sdk@2.21.1` and `@medusajs/types@2.21.1` — plus
`@medusajs/medusa@2.21.1` for the server facts the SDK does not carry (the
publishable-key boundary with no customer-authentication middleware on
either route, the required `cart_id` on both surfaces, and the list
validator defaults the route then ignores). Everything below was verified
against the published packages themselves, not documentation alone.

## Pinned routes (2)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | GET | `/store/shipping-options` | — | `StoreShippingOptionListResponse` | `StoreGetShippingOptionList` | publishable-key | `listCartOptions` |
| 2 | POST | `/store/shipping-options/{id}/calculate` | `StoreCalculateShippingOptionPrice` | `StoreShippingOptionResponse` | `StoreShippingOptionCalculateParams` | publishable-key | `calculate` |

- Both routes are covered by the `sdk.store.fulfillment` namespace of the
  pinned SDK — there is **no** `shippingOption` namespace; the option
  surface hangs off fulfillment because upstream options belong to the
  fulfillment module (verified against the published SDK sources).
- The list is **not paginated upstream**: the pinned `StoreGetShippingOptions`
  validator defaults `offset: 0` / `limit: 20`, but the pinned list route
  ignores the page and responds the non-paginated
  `StoreShippingOptionListResponse`, which carries no `count` / `offset` /
  `limit` at all. The defaults are recorded in the manifest as upstream
  facts only; the Ceto read model refuses the dead keys instead of serving
  a pagination the envelope cannot carry (hence no `*_LIST_MAX_LIMIT` page
  bound on this manifest, unlike every paged Ceto list).

## Auth and error semantics

Both routes are guest-dispatchable Store reads — no customer session exists
and the publishable key is the only credential, required exactly as on
every Store route (carts Recorded Decision 5: boundary validation only,
never persisted). The key is matched with a constant-time comparison
against the `ceto_cart.publishable_keys` site configuration, and the key's
region / sales-channel scope is enforced against the resolved cart through
the shared `guard` seam before anything is priced — the identical
`CartPublishableKey.check_reference` the cart mutations invoke, applied to
the read's resolved `Ceto Cart Reference`. The error contract is the stable
Medusa set:

- `401 unauthorized` — missing or unknown publishable key.
- `403 not_allowed` — a valid key whose configured region / sales-channel
  scope differs from the resolved cart's.
- `400 invalid_data` — every rejected query or body key (see
  [Query behavior](#query-behavior)), a blank `cart_id`, a `data` payload
  that is not an object, and a cart that cannot anchor a quote at all (no
  identity, company or currency — a broken cart is refused like on every
  cart surface, never silently served empty).
- `404 not_found` — an unknown, claimed-elsewhere or non-open cart (the
  masked `404` of the whole cart surface), and — deliberately — every
  option id no registered provider serves for that cart: unknown,
  disabled, foreign-company, country-ineligible, or not a `so_` token at
  all. The option space stays opaque; nothing distinguishes a malformed
  token from another tenant's option.

A failed quote source never becomes a client-facing error: a registered
provider that raises mid-listing, a hook path that does not resolve and a
registrant without the provider shape are logged and skipped, so one broken
provider can only contribute nothing, never fail a read.

## Opaque option ids

The public option id is the opaque, stable token
`so_<base64url(provider_id + ':' + option_key)>` — the provider id joined
with the provider's own option key, URL-safe-base64 encoded without
padding. It is **never** the raw ERPNext `Shipping Rule` name on this
surface.

- The encoding is reversible: decoding recovers `(provider_id, option_key)`,
  so the registry routes a public id to the provider that minted it without
  any lookup table. The separator lives inside the encoded payload, which
  is why a provider id may never contain `:`; an option key may contain
  anything, because the split takes the first separator.
- Anything the codec could not have minted — wrong prefix, foreign
  characters, broken base64, a missing separator, an empty identity part —
  raises the domain `MalformedShippingOptionIdError`, which the service
  masks into the same `404 not_found` as an unknown option.
- Listing and resolution are first-wins: the built-in `erpnext` provider
  registers first and cannot be displaced, and the first quote minting a
  public id wins, so an id can never resolve ambiguously.
- The **cart apply** (`POST /store/carts/{id}/shipping-methods`) is the one
  surface that also accepts the legacy raw `Shipping Rule` name beside the
  opaque token — a well-formed `so_` token of the built-in provider decodes
  to its option key, the rule name, and resolves exactly like the raw name.
  A malformed token, a foreign provider's token and a well-formed token of
  an unknown rule are the apply's existing `400 invalid_data`
  "Shipping option not found" rejection, with the cart untouched.
- The applied method **echoes the last supplied id form**: the apply records
  the supplied option id on the `Ceto Cart Reference` and the serializer
  serves it back, so an option applied through its `so_` id keeps that
  identity on every cart read. The echo falls back to the raw rule name
  when no usable record stands (carts predating the record, a stale record
  naming another rule, a foreign-provider or malformed record).

## ERPNext Shipping Rule mapping and eligibility

The built-in `erpnext` provider serves options straight from ERPNext
`Shipping Rule` masters. One eligible rule is one option:

- **Eligibility** mirrors what the cart apply accepts and what ERPNext's own
  `ShippingRule.apply` would apply: the rule must be enabled, a
  `shipping_rule_type: "Selling"` rule, and belong to the cart's company.
  Disabled, buying-side and foreign-company rules never serve.
- **No-address nuance**: a rule restricted to `Shipping Rule Country` rows
  stays eligible for a cart **without a shipping address** — ERPNext
  validates countries only when the document carries one, and the adapter
  keeps that exact behaviour, so a listed option is never one ERPNext would
  refuse at apply time (and vice versa). Once an address exists, a country
  outside the rule's list drops the option from the listing and masks the
  calculate.
- **Identity mapping**: the option key is the rule name, the served `name`
  is the rule `label`, and `provider` is the built-in `erpnext` provider
  reduced to `{id, is_enabled: true}` — enabled by definition, since its
  rules would not serve otherwise.
- **Rate resolution** reproduces exactly what `ShippingRule.apply` books:
  a `Fixed` rule serves its `shipping_amount`; `Net Total` and
  `Net Weight` rules walk their condition rows in stored row order (the
  same order `get_shipping_amount_from_rules` walks — the doctype's
  validate renumbers rows, it never reorders them) and the first row whose
  open-ended or inclusive range contains the resolved value wins,
  defaulting to 0. The value priced is the cart's own saved state —
  `base_net_total` or `total_net_weight` from the Quotation.
- **Currency nuance**: the rate resolves in the company currency; a cart in
  a foreign currency gets the same division by the document conversion rate
  and two-decimal `flt` rounding the application performs, so the quote
  equals the charge row the applied method books. The cart surface pins
  "same currency" as rate 1, so the context builder normalizes a falsy
  conversion rate to 1.0 instead of dividing by zero.
  `calculated_price.currency_code` is the cart's own currency, lowercased
  to Medusa's code convention — never the company currency.
- **Itemless carts**: option reads are pure reads over the saved cart, so
  the quote resolves from whatever the saved document carries — ERPNext's
  empty-cart baseline zeroes the totals, and a `Fixed` rule still quotes
  its `shipping_amount` from it. The *charge* is a different surface: the
  apply books no charge row on an itemless cart (ERPNext skips the rule
  application without lines), as pinned in
  [docs/carts/endpoints.md](../carts/endpoints.md).
- **Batched reads**: a listing resolves every rule in a fixed number of
  batched queries — heads, then both child tables (conditions, countries)
  of every head at once — however many rules serve; a listing can never
  degrade into per-rule reads. Providers only read: a quote is computed
  from the context and the provider's own masters, never written back to
  the cart.

## Provider hook

The option space is provider-neutral. Downstream apps register additional
providers through the `ceto_shipping_providers` hook:

```python
ceto_shipping_providers = ["my_app.shipping.CustomShippingProvider"]
```

- Each entry is a dotted path to a provider class (instantiated with no
  arguments), a zero-argument factory returning an instance, or a ready
  instance. A provider exposes a nonblank `id` (the left side of the
  `so_` token) and a `list_options(context)` method returning
  `ShippingOptionQuote` values; `get_option(context, option_key)` is
  optional — providers without it are resolved by scanning their listing
  (`OptionScanningProvider` bakes that default in).
- **Determinism**: the built-in `erpnext` provider registers first, hook
  providers follow in hook declaration order, and the first provider
  claiming an id wins — the same site configuration always produces the
  same registry, provider order and option order, and `erpnext` always
  means the built-in provider.
- **Isolation**: a path that does not resolve, a factory that raises, an
  object without the provider shape, a quote of another provider's
  identity or another currency than the cart's, and a provider failing
  mid-read are all logged and skipped — one broken provider can never
  fail an option read, it can only contribute nothing.
- Hook paths come exclusively from installed-app hooks configuration,
  never from request input.

## Query behavior

The pinned query contracts live in
`ceto/types/http/store/shipping_options/queries.py` and are validated at
the boundary before anything resolves. The list accepts exactly `cart_id`
(required, never blank — the one scoping key the route resolves) plus the
optional `is_return` flag. Everything else is refused as `400 invalid_data`
instead of silently ignored or clamped: the dead `FindParams` pagination
(`limit`, `offset` — the pinned route ignores them and its envelope cannot
carry them), the `fields` selector, the `order` sort, the `$and`/`$or`
combinators, and any unknown key.

`is_return=true` serves the **honest empty option set**, not an error:
ERPNext `Selling` rules have no return-rate source, so no return option can
ever be listed. The cart still resolves first — a masked cart is `404
not_found` with or without the flag.

The calculate route accepts **no query at all**: upstream validates a bare
`SelectParams` (the pinned `HttpTypes` publish no named type and the pinned
SDK sends no query), and because the router merges query parameters into
the same argument mapping as the body, every query key — `fields` as much
as anything else — rides into the strict body contract and fails as `400
invalid_data`.

Ceto is stricter than the pinned upstream validators, which strip unknown
keys: both Ceto models are `extra="forbid"`, so a new Medusa field fails
loudly instead of being silently dropped, like on every core payload.

## Response projection

The list responds the exact non-paginated pinned body —
`{"shipping_options": [...]}` with no `count` / `offset` / `limit` and none
may grow silently — and calculate responds
`{"shipping_option": StoreCartShippingOption}`; both envelopes carry the
same entity, so the pinned list member's
`service_zone.fulfillment_set.location.address` expansion collapses into
the shared projection. The served columns:

| Field | Served value |
|---|---|
| `id` | the opaque `so_` token (see [Opaque option ids](#opaque-option-ids)) |
| `name` | the rule `label` (the provider's own display name) |
| `price_type` | always the pinned `flat` — every option is a deterministic cart-specific quote, not a stored list price |
| `provider` | `{id, is_enabled: true}` of the option's provider (`erpnext` built-in) |
| `amount` | the ERPNext-resolved rate for this cart, plain float per the repository money convention; `0` is the honest default when a rate resolves to nothing |
| `is_tax_inclusive` | always `false` — the Selling charge row books without tax allocation |
| `calculated_price` | the shipping-specific subset `{calculated_amount, original_amount, currency_code, is_calculated_price_tax_inclusive}` — all four columns required, `calculated_amount` = `original_amount` = `amount`, `currency_code` the cart's lowercased currency, tax-inclusive mirroring `is_tax_inclusive`; the subset is never partial — when no quote resolves at all the whole object stays absent instead of a zero-filled stub |
| `data`, `metadata` | pinned nullable columns with no ERPNext source: served `null`, never fabricated |

The remaining fulfillment-module columns — `service_zone_id`,
`shipping_profile_id`, the `type` relation, the stored `prices` and
`insufficient_inventory` — have no ERPNext source and are **dropped
entirely, never stubbed** (the products-slice projection precedent).

## List → calculate → add-to-cart parity

The three surfaces close the round-trip on the same identity and amount —
pinned end-to-end by
`ceto.tests.api.store.test_shipping_options_cart_roundtrip`:

1. **List** serves every eligible rule for the cart under its opaque `so_`
   id with its ERPNext-resolved amount.
2. **Calculate** resolves one of those ids against the same cart context
   and serves the identical projection — same id, same name, same amount
   (the list and calculate answers are asserted equal in the API tests).
3. **Add-to-cart** (`POST /store/carts/{id}/shipping-methods`) accepts that
   same id: the opaque token decodes to the built-in provider's option key
   (the rule name) and applies exactly like the legacy raw name. The
   applied method echoes the supplied id back with the option's amount and
   name — no re-derivation anywhere — and the echo persists with the cart.
   Re-applying the same id is idempotent: one `Actual` charge row, the
   grand total carries the charge exactly once, and the reference write is
   skipped. Switching the supplied id form (opaque ↔ legacy raw) switches
   the echo to the last supplied form.
4. ERPNext stays the pricing authority: the amount the quote serves is the
   amount the controller books as the Quotation's `Actual` charge row (the
   service suite prices quotes against real ERPNext applications), and the
   cart totals reconcile under the Medusa semantics pinned in
   [docs/carts/endpoints.md](../carts/endpoints.md).

## Implemented routes

The shipping slice registers exactly these two routes; the whole pinned
shipping-option inventory is served.

### `GET /store/shipping-options` — `ceto.api.store.shipping_options.list_shipping_options`

- Guest-dispatchable Store route requiring the `x-publishable-api-key`
  header, validated at the boundary against the `ceto_cart.publishable_keys`
  configuration and never persisted; the key's region / sales-channel
  scope is enforced against the resolved cart through the shared `guard`
  seam (`403 not_allowed` on mismatch, before anything is priced).
- The pinned `StoreGetShippingOptionList` validates the query before
  anything resolves: `cart_id` is the required scope, `is_return=true`
  serves the empty option set, and every other key — the dead pagination,
  `fields`, `order`, `$and`/`$or`, anything unknown — fails as `400
  invalid_data`.
- Resolves the open cart through the shared cart access (unknown,
  claimed-elsewhere and non-open carts are the same masked `404
  not_found`), builds the frozen quote context from the cart's two
  committed records, and concatenates the provider registry's quotes in
  deterministic order — eligible ERPNext `Selling` rules by rule name,
  hook providers following in declaration order, duplicate ids keeping
  the first quote.
- Reads only: the request never writes the cart, and a failing provider
  contributes nothing instead of failing the read.

### `POST /store/shipping-options/{id}/calculate` — `ceto.api.store.shipping_options.calculate_shipping_option_price`

- Same publishable-key boundary and cart masking as the list.
- The pinned `StoreCalculateShippingOptionPrice` body is validated
  strictly: `cart_id` is required and never blank, `data` must be an
  object when present, and unknown keys fail as `400 invalid_data` —
  including any query parameter, because the router merges query
  parameters into the same argument mapping and the pinned calculate
  query accepts nothing.
- The optional provider `data` is accepted for request compatibility only
  and never persisted: the ERPNext compatibility field for a shipping
  option is the `Shipping Rule` master, which carries no provider payload,
  so there is nothing to store it in (a route test pins that nothing about
  the payload reaches cart metadata or Quotation state).
- The id resolves through the registry against this cart's context: a
  token no registered provider serves for the cart — unknown, disabled,
  foreign-company, country-ineligible, or not a `so_` token at all — is
  the same masked `404 not_found` as an unknown cart.

## Deliberate omissions and deviations

- **No pagination** — the upstream list route is not paginated (the
  validator's 0/20 defaults are dead parameters), so Ceto refuses
  `limit`/`offset` instead of bounding a page the envelope cannot carry.
- **No `is_return` options** — `is_return=true` serves the empty set
  rather than an error: ERPNext `Selling` rules have no return-rate source.
- **No `fields` selector, search, filters, sort expressions or combinators
  on either route** — the projection is fixed; every such key is rejected
  as `400 invalid_data` (see [Query behavior](#query-behavior)).
- **No fulfillment-module columns** — `service_zone_id`,
  `shipping_profile_id`, `type`, stored `prices`,
  `insufficient_inventory` and the `WithServiceZone` address expansion are
  dropped entirely, never stubbed.
- **No provider `data` persistence** — `data` is accepted on calculate for
  request compatibility, validated, and dropped; `data` / `metadata` are
  served `null`, never fabricated.
- **Stricter-than-upstream validation** — the pinned upstream validators
  strip unknown keys; Ceto rejects them (`extra="forbid"`) like on every
  core payload, so new Medusa fields fail loudly instead of being silently
  dropped.
- **No gateway rates** — the built-in provider serves master-driven
  ERPNext quotes. **Shipgi**, the shipment-gateway app that owns provider
  integrations, is currently a skeleton with no rate API; the
  `ceto_shipping_providers` hook is the seam where dynamic provider rates
  plug in, without touching this contract.
- **Read-only surface** — listing and calculating never write the cart;
  the only surface that applies an option (and persists state) is the cart
  shipping-methods apply, which keeps accepting the legacy raw rule name
  beside the opaque token.
