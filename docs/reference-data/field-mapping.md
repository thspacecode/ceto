# Store Reference Data — Medusa → Ceto/ERPNext Field Mapping (Phase 1 slice A)

Classification legend for every mapping row:

- **direct** — the Medusa field maps 1:1 onto a config key or an ERPNext/
  Frappe record field (possibly with type coercion).
- **derived** — the Medusa field is computed from Ceto configuration or
  ERPNext/Frappe records.
- **gap** — no Ceto/ERPNext equivalent exists; the field is omitted (the
  pinned contract permits it) and never fabricated.

## Recorded decisions

1. **Config-backed regions, no new DocType.** Regions are the private
   `ceto_cart.regions` site configuration. A region is *servable* when its
   effective configuration — the top-level `ceto_cart` defaults overlaid by
   the region entry, exactly the overlay `CartConfiguration.resolve`
   applies — resolves all three commerce anchors: an existing Company, an
   existing selling Price List, and a currency (the entry's `currency` key,
   else the price list currency — the identical rule the cart service uses,
   shared through `ceto.config.cart`, so cart config and reference data
   cannot drift). An explicit `currency` that conflicts with its selling
   Price List's own currency is unservable too: carts price in the Price
   List's currency (the quotation pins its conversion rates at 1), so no
   cart could ever use the region. Unservable regions are not errors: they
   never appear in the list and mask as `404` on detail, so a broken
   overlay can never surface a region no cart could use.
2. **The currency list is scoped, not total.** It is exactly the distinct
   currencies the servable regions resolve to — never the full ERPNext
   currency table. Region validity is the single gate: an ERPNext-disabled
   currency a valid region references still projects (a master-data flag
   must not silently break the storefront's region↔currency join), while a
   currency no valid region references is invisible — `404` on detail,
   absent from the list.
3. **Locales are the enabled Frappe `Language` records**, ordered by code,
   with one **labeled Ceto extension** on the response: `default_locale`,
   resolved deterministically — `ceto_cart.default_locale` when it names an
   enabled language, else the site default language (`System
   Settings.language`) when enabled, else `en` when enabled, else the first
   enabled language by code, else `None`. The route shape itself is pinned
   to `@medusajs/types@2.21.1` (upstream ships it behind the `translation`
   feature flag; Ceto serves it unconditionally, on Ceto-owned
   provisioning).
4. **Config-backed timestamps are never fabricated.** Regions come from
   site configuration and carry no record timestamps: `created_at` /
   `updated_at` stay `None` (the pinned contract marks them optional).
   Currency and locale projections of real records serve real timestamps —
   currency `created_at` / `updated_at` are the ERPNext `creation` /
   `modified` of the `Currency` record.
5. **Lowercase currency codes.** Medusa codes are lowercase ISO codes;
   ERPNext names its `Currency` records with the uppercase code. Projections
   lowercase; the detail route resolves case-insensitively.

## Region → `ceto_cart` configuration

| Medusa `StoreRegion` field | Ceto source | Classification |
|---|---|---|
| `id` | the `ceto_cart.regions` key (region id, e.g. `reg_us`) | direct |
| `name` | the region entry's optional `name` key — a **Ceto config extension**; falls back to the region id | derived |
| `currency_code` | entry `currency` key, else the selling Price List currency (shared rule, `ceto.config.cart`); lowercased | derived |
| `automatic_taxes` | always `true` — a Ceto behavioral invariant: ERPNext Selling documents always recalculate their tax template on save, so region taxes are never manual | derived |
| `countries` | none — the config schema has no country list; the pinned relation stays `None` (geo→region mapping is deferred) | gap |
| `payment_providers` | dropped from the projection model entirely — no payment-provider projection exists in Ceto yet | gap |
| `metadata` | none — the config schema has no region metadata | gap |
| `created_at`, `updated_at` | none — config-backed, never fabricated (Recorded Decision 4) | gap |

The optional `name` key is the only addition to the cart region config
schema. The cart service ignores it (extra keys are overlay no-ops there),
so no cart behavior changes in this slice.

## Currency → ERPNext `Currency`

| Medusa `StoreCurrency` field | ERPNext `Currency` field | Classification |
|---|---|---|
| `code` | record name (uppercase ISO), lowercased | direct |
| `name` | `currency_name`, falling back to the record name | direct |
| `symbol` | `symbol` (empty stays `None`) | direct |
| `symbol_native` | none — ERPNext stores one symbol per currency; no native-vs-plain distinction is ever fabricated | gap |
| `decimal_digits` | fraction placeholders of `number_format` (`#,###.##` → 2, `#,###` → 0, unset → `None`) | derived |
| `rounding` | `smallest_currency_fraction_value` (unset/0 stays `None`) | derived |
| `created_at`, `updated_at` | `creation` / `modified` of the `Currency` record — real record timestamps (Recorded Decision 4) | direct |
| `deleted_at` | none — ERPNext deletes currencies hard; there is no soft-delete tombstone | gap |

Scope: only the currencies referenced by servable regions (Recorded
Decision 2). The pinned 2.21.1 type marks `symbol_native`, `decimal_digits`,
`rounding`, `created_at`, `updated_at` and `deleted_at` non-nullable, but
the pinned store list itself serves a field-selected subset (the core query
config defaults exclude the timestamps); Ceto keeps every column optional in
the contract and omits what has no honest source — the same policy the cart
line items already record.

## Locale → Frappe `Language`

| Medusa `StoreLocale` field | Frappe `Language` field | Classification |
|---|---|---|
| `code` | `Language` record name (`language_code`) | direct |
| `name` | `language_name`, falling back to the code | direct |
| `default_locale` (response column) | **labeled Ceto extension** — the deterministic chain in Recorded Decision 3; not part of `@medusajs/types@2.21.1` | derived |

Only enabled languages are listed. The pinned upstream response is unpaged
and carries no timestamps; Ceto adds exactly one column, `default_locale`,
and nothing else.
