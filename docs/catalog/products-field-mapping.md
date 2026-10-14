# Store Products — Medusa → Ceto/ERPNext Field Mapping (Phase 3 contract slice)

Classification legend for every mapping row (same convention as
`docs/catalog/field-mapping.md`):

- **direct** — the Medusa field maps 1:1 onto a stored Ceto catalog record
  field or an ERPNext/Frappe record field (possibly with type coercion).
- **derived** — the Medusa field is computed from Ceto configuration or
  ERPNext/Frappe records.
- **gap** — no Ceto/ERPNext equivalent exists; the field is omitted (the
  pinned contract permits it) and never fabricated.

Sources: pinned `@medusajs/types@2.21.1` (`http/product/store`), the
`sdk.store.product` / `sdk.store.productOption` namespaces of
`@medusajs/js-sdk@2.21.1` and the store routes/validators of
`@medusajs/medusa@2.21.1` (see
[products-endpoints.md](./products-endpoints.md)). This slice pins the
contract only — no route is registered and no README row flips until the
products behavior slice lands.

## Recorded decisions (products slice)

1. **The published assortment is scoped by the configured catalog
   category roots.** A product is published exactly when it belongs to the
   published taxonomy — the ERPNext `Item Group` tree inside the
   `ceto_catalog.category_roots` storefront roots
   (taxonomy Recorded Decision 1 in `docs/catalog/field-mapping.md`), so
   the products projection reuses the category slice's publication rule
   instead of inventing a second one. With no roots configured the
   assortment publishes nothing, exactly like the category directory.
   Upstream agrees in spirit: the 2.21.1 product routes default-filter
   `status: published` server-side and accept no client `status` filter —
   publication is a projection decision, never a served flag. The
   item-to-category link resolution ships with the behavior slice.
2. **Returned variant IDs stay the exact ERPNext `Item` codes.** A Medusa
   variant is an ERPNext `Item` in this integration; the variant `id` is
   the verbatim `item_code` — never minted, never transformed — so a
   storefront can carry a variant id into the cart slice unchanged. The
   contract keeps `id` required and never derives a public prefix for it.
3. **Category ids are the existing derived category ids.** Product
   `categories` embed the same `StoreProductCategory` projections the
   category slice serves: `pcat_…` ids derived deterministically from the
   `Item Group` node name (`ceto.services.catalog.product_categories`),
   so a product's category id is always resolvable against
   `/store/product-categories`.
4. **Collection-to-item and product-type-to-item links are Ceto-owned.**
   No ERPNext master links an `Item` to a `Ceto Collection` or a
   `Ceto Product Type`, so both links are Ceto data-model decisions: the
   contract keeps `collection_id` / `collection` and `type_id` / `type`
   optional and they stay unpopulated until the link model lands with the
   behavior slice. The taxonomy Recorded Decisions 2–4 (Ceto-stored
   collections, minted `ptyp_…` type ids, deferred membership) carry over
   unchanged.
5. **The variants surface is canonical `GET /store/product-variants`.**
   The pinned inventory carries exactly one variants route — the list. The
   upstream server also serves `GET /store/product-variants/{id}` (since
   2.11.2), but it stays out of the pinned inventory and the README
   inventory lists only the list route; a variant is always reachable
   through its product.
6. **Cart publication enforcement and services are out of scope.** This
   slice pins no service, registers no route and prices nothing: the
   pricing-context query keys (`region_id`, `country_code`, `province`,
   `cart_id`) are refused as unknown fields, `calculated_price` and
   `inventory_quantity` are dropped from the projection models, and the
   published-items-only cart rules are a later slice's decision.

## Product → ERPNext `Item` / Ceto catalog

A product is the published assortment unit above the sellable variant: the
ERPNext `Item` (its `item_code` is the variant id, decision 2) joined with
the Ceto-owned catalog surfaces. The product public `id` minting is a
behavior-slice decision and is deliberately not fixed here.

| Medusa `StoreProduct` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | stable public id of the published product — minting/derivation decided with the products behavior slice | derived |
| `title` | the item name (`Item` `item_name` / the Ceto catalog title column) | direct |
| `handle` | the product's stable URL segment — slug decision lands with the behavior slice | derived |
| `subtitle` | none — ERPNext carries no subtitle; never fabricated | gap |
| `description` | `Item` `description` (the web description overlay is a behavior-slice choice) | direct |
| `is_giftcard` | none — no ERPNext gift-card flag; stays `None` | gap |
| `discountable` | none — promotion eligibility is the carts/promotions slice's decision | gap |
| `status` | none served — publication is the projection decision (decision 1); upstream pins `status: published` server-side | gap |
| `thumbnail` | `Item` `image` (or the Website Item image overlay) | derived |
| `width`, `length`, `height`, `weight` | none — `Item` carries no dimension columns; never fabricated | gap |
| `origin_country` | `Item` `country_of_origin` when set | direct |
| `hs_code`, `mid_code` | none — `Item` carries no HS/MID code columns | gap |
| `material` | none — `Item` carries no material column | gap |
| `collection_id`, `collection` | the Ceto-owned item link — unpopulated until decision 4 lands | gap |
| `type_id`, `type` | the Ceto-owned item link — unpopulated until decision 4 lands | gap |
| `categories` | the published `Item Group` projections of the item's groups (decisions 1 and 3) | derived |
| `tags` | the Frappe user-tag projections of the item's Tag Link rows | derived |
| `variants` | the item's sellable projections — each an ERPNext `Item` (decision 2) | derived |
| `options` | the item's option projections (see below) | derived |
| `images` | the item's image set — source and ranking decided with the behavior slice | derived |
| `external_id` | none — no external system assigns product ids | gap |
| `metadata` | none — the config schema has no product metadata | gap |
| `created_at`, `updated_at` | the served record's `creation` / `modified` once the projection lands (Recorded Decision 8, `docs/catalog/field-mapping.md`) | direct |
| `deleted_at` | none — the catalog layer deletes hard | gap |

## Product Variant → ERPNext `Item`

| Medusa `StoreProductVariant` field | ERPNext `Item` source | Classification |
|---|---|---|
| `id` | the exact `Item` `item_code` — verbatim, never minted (decision 2) | direct |
| `title` | the variant's display title — projection decision with the behavior slice | derived |
| `sku` | the `Item` `item_code` serves as the SKU surface | direct |
| `barcode` | the item's `barcodes` rows (first barcode) | derived |
| `ean`, `upc` | the item's `barcodes` rows by barcode type | derived |
| `thumbnail` | `Item` `image` | derived |
| `images` | the item's image set (see the product row) | derived |
| `allow_backorder` | none — inventory policy is out of scope (decision 6) | gap |
| `manage_inventory` | none — inventory behavior is out of scope (decision 6) | gap |
| `variant_rank` | none — no sibling-ranking source exists; stays `None` | gap |
| `product_id`, `product` | the public id of the owning product | derived |
| `options` | the item's option-value projections (see below) | derived |
| `hs_code`, `origin_country`, `mid_code`, `material` | as on the product row (`country_of_origin` is the only direct source) | gap |
| `weight`, `length`, `height`, `width` | none — `Item` carries no dimension columns | gap |
| `calculated_price` | dropped from the projection model entirely — pricing is out of scope (decision 6) | gap |
| `inventory_quantity` | dropped from the projection model entirely — inventory is out of scope (decision 6) | gap |
| `metadata` | none — the config schema has no variant metadata | gap |
| `created_at`, `updated_at` | the `Item` record's `creation` / `modified` once served (Recorded Decision 8) | direct |
| `deleted_at` | none — ERPNext deletes Items hard | gap |

## Product Option → Ceto-owned projection

ERPNext has no product-option master; the option/value shape (Item
attributes versus Ceto-owned masters) is a behavior-slice decision, so the
contract pins only the served shape and never fabricates a source.

| Medusa `StoreProductOption` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | stable public option id — minting decided with the behavior slice | derived |
| `title` | the option label (e.g. `Color`) | direct |
| `is_exclusive` | none — the exclusive/global option semantics are a Ceto decision | gap |
| `product` | the owning product projection | derived |
| `values` | the option's value projections (below) | derived |
| `metadata` | none — no option metadata surface | gap |
| `created_at`, `updated_at` | the owning record's timestamps once served (Recorded Decision 8) | direct |
| `deleted_at` | none — options delete with their product | gap |

| Medusa `StoreProductOptionValue` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | stable public value id — minting decided with the behavior slice | derived |
| `value` | the value label (e.g. `Red`) | direct |
| `rank` | none — no value-ranking source exists; stays `None` | gap |
| `option_id`, `option` | the owning option projection | derived |
| `metadata` | none — no value metadata surface | gap |
| `created_at`, `updated_at` | the owning record's timestamps once served (Recorded Decision 8) | direct |
| `deleted_at` | none — values delete with their option | gap |

## Product Image → ERPNext `File` / `Item` image

| Medusa `StoreProductImage` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | stable public image id — minting decided with the behavior slice | derived |
| `url` | the served image URL (`Item` `image` / the item's File attachments) | derived |
| `rank` | none — no image-ranking source exists; stays `None` | gap |
| `metadata` | none — no image metadata surface | gap |
| `created_at`, `updated_at` | the owning record's timestamps once served (Recorded Decision 8) | direct |
| `deleted_at` | none — images delete with their product | gap |

## Auth and error semantics

Shared with the whole Store read surface — recorded once in
[products-endpoints.md](./products-endpoints.md): publishable-key-only
guest reads (`401 unauthorized`), strict extra-forbid query validation and
out-of-bounds pagination (`400 invalid_data`), and masked `404 not_found`
for unknown or unpublished ids.
