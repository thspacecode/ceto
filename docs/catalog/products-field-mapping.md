# Store Products — Medusa → Ceto/ERPNext Field Mapping (Phase 3 products slice)

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
[products-endpoints.md](./products-endpoints.md)). The slice's storage,
publication and served projection have landed — the publication authority
(`ceto.services.catalog.publication`), the Ceto-owned merchandising link
(Recorded Decision 4) and the batched product service
(`ceto.services.catalog.families` assembling the assortment,
`ceto.services.catalog.products` serializing it and
`ceto.services.catalog.pricing` resolving region prices) — while the route
surface stays pinned-only: no route is registered, no API module ships and
no README row flips until the products routes slice lands.

## Recorded decisions (products slice)

1. **The published assortment is scoped by the configured catalog
   category roots.** A product is published exactly when it belongs to the
   published taxonomy — the ERPNext `Item Group` tree inside the
   `ceto_catalog.category_roots` storefront roots
   (taxonomy Recorded Decision 1 in `docs/catalog/field-mapping.md`). The
   rule lives once, in the publication authority
   `ceto.services.catalog.publication` — an enabled, sales, non-template
   `Item` whose group sits inside the roots — and every consumer (the
   category directory, the cart's variant resolver, the products
   projection) asks it instead of re-deriving the boundary. With no roots
   configured the assortment publishes nothing, exactly like the category
   directory. Upstream agrees in spirit: the 2.21.1 product routes
   default-filter `status: published` server-side and accept no client
   `status` filter — publication is a projection decision, never a served
   flag. The item-to-category link rides the same boundary: a product
   embeds only the published projection of its own `Item Group` node.
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
   `Ceto Product Type`, so both links are Ceto data-model decisions and
   land as one cohesive record: the `Ceto Product Merchandising` DocType
   is named by the exact `Item` code — one record per `Item`, the
   uniqueness the served singular `collection_id` / `type_id` semantics
   need — and carries the optional `collection` and `product_type` links,
   at least one of which is required. Deleting a master detaches its
   references and a record left without any link is deleted outright;
   deleting the `Item` itself stays blocked while its record exists. The
   served projection embeds the stored projections verbatim — the same
   `StoreCollection` / `StoreProductType` objects the collection and type
   directories serve — and the contract keeps `collection_id` /
   `collection` and `type_id` / `type` optional, so an unlinked product
   serves all four as `None`. The taxonomy Recorded Decisions 2–4
   (Ceto-stored collections, minted `ptyp_…` type ids, deferred
   membership) carry over unchanged.
5. **The variants surface is canonical `GET /store/product-variants`.**
   The pinned inventory carries exactly one variants route — the list. The
   upstream server also serves `GET /store/product-variants/{id}` (since
   2.11.2), but it stays out of the pinned inventory and the README
   inventory lists only the list route; a variant is always reachable
   through its product.
6. **Pricing is region-scoped through the cart price-list authority;
   inventory stays out of scope.** A presented `region_id` resolves
   through the cart configuration — the same price-list and currency
   anchors a cart create resolves — and prices the surface's variants with
   one batched, anonymous `Item Price` read per page
   (`ceto.services.catalog.pricing`): blank-party, blank-batch rows of the
   region's selling Price List inside their validity window, selected in
   the order ERPNext's `get_item_price` uses, the rate served as the
   `calculated_price` amount in the list's own currency. No `region_id` —
   or a blank one — means no pricing: `calculated_price` stays absent,
   never a fabricated zero. `inventory_quantity` remains dropped from the
   projection model: inventory is out of scope and Ceto does not stub
   contracts that do not exist yet. The published-items-only cart rule, by
   contrast, has landed: the cart's single variant touchpoint
   (`ceto.services.carts.variants.resolve_item_code`) resolves a variant
   id through the publication authority, so a cart can only ever carry a
   published sellable item — a variant of a template family or a
   standalone item, never the template — and every refusal (unknown,
   disabled, non-sales, template, outside the roots) is the same
   `invalid_data` error the resolver has always masked unknown ids with.
7. **Public identities are derived, never stored.** The product id is
   `prod_` plus a SHA-256 truncation of the exact `Item` code, the
   option/value ids hash the family code with the attribute (and value)
   and the image id hashes the item — all opaque, stable and addressable
   with no core schema change, the same derivation pattern the `pcat_…` /
   `ptag_` ids use. The `handle` is the slug of the item title with the
   item code as fallback; a title slug two served products share
   disambiguates every colliding member with a digest suffix, so handles
   stay unique and the mapping stays deterministic for a given assortment.

## Product → ERPNext `Item` / Ceto catalog

A product is the published assortment unit above the sellable variant: an
eligible family head or a standalone published `Item` (decision 1) joined
with the Ceto-owned catalog surfaces. Its public `id` / `handle` are
derived hashes, never stored (decision 7).

| Medusa `StoreProduct` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | `prod_` + a SHA-256 truncation of the exact `Item` code — opaque, stable, addressable (decision 7) | derived |
| `title` | the item name (`Item` `item_name` / the Ceto catalog title column) | direct |
| `handle` | the slug of the item title, item code as fallback; a shared slug takes a digest suffix on every colliding member (decision 7) | derived |
| `subtitle` | none — ERPNext carries no subtitle; never fabricated | gap |
| `description` | `Item` `description` when set | direct |
| `is_giftcard` | none — no ERPNext gift-card flag; stays `None` | gap |
| `discountable` | none — promotion eligibility is the carts/promotions slice's decision | gap |
| `status` | none served — publication is the projection decision (decision 1); upstream pins `status: published` server-side | gap |
| `thumbnail` | `Item` `image` when set | direct |
| `width`, `length`, `height`, `weight` | none — `Item` carries no dimension columns; never fabricated | gap |
| `origin_country` | `Item` `country_of_origin` when set | direct |
| `hs_code`, `mid_code` | none — `Item` carries no HS/MID code columns | gap |
| `material` | none — `Item` carries no material column | gap |
| `collection_id`, `collection` | the `Ceto Product Merchandising` record's `collection` link with its embedded `StoreCollection` projection (decision 4) | direct |
| `type_id`, `type` | the `Ceto Product Merchandising` record's `product_type` link with its embedded `StoreProductType` projection (decision 4) | direct |
| `categories` | the published `Item Group` projections of the item's groups (decisions 1 and 3) | derived |
| `tags` | the Frappe user-tag projections of the item's Tag Link rows | derived |
| `variants` | the item's sellable projections — each an ERPNext `Item` (decision 2) | derived |
| `options` | the item's option projections (see below) | derived |
| `images` | the `Item` `image` — the only image source; one served image when set (decision 7) | derived |
| `external_id` | none — no external system assigns product ids | gap |
| `metadata` | none — the config schema has no product metadata | gap |
| `created_at`, `updated_at` | the `Item` record's `creation` / `modified` (Recorded Decision 8, `docs/catalog/field-mapping.md`) | direct |
| `deleted_at` | none — the catalog layer deletes hard | gap |

## Product Variant → ERPNext `Item`

| Medusa `StoreProductVariant` field | ERPNext `Item` source | Classification |
|---|---|---|
| `id` | the exact `Item` `item_code` — verbatim, never minted (decision 2) | direct |
| `title` | the item name, like its owning product | direct |
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
| `calculated_price` | the region-aware `StoreCalculatedPrice` when a `region_id` resolves through the cart price-list authority; absent without one — never a fabricated zero (decision 6) | derived |
| `inventory_quantity` | dropped from the projection model entirely — inventory is out of scope (decision 6) | gap |
| `metadata` | none — the config schema has no variant metadata | gap |
| `created_at`, `updated_at` | the `Item` record's `creation` / `modified` (Recorded Decision 8) | direct |
| `deleted_at` | none — ERPNext deletes Items hard | gap |

## Product Option → Ceto-owned projection

ERPNext has no product-option master; the shape is decided here as
landed: a family option is the head template's `Item Variant Attribute`
row, its values are only those observed on *published* variants and the
ids are derived hashes, never stored (decision 7).

| Medusa `StoreProductOption` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | `opt_` + a hash of the family code and the attribute title (decision 7) | derived |
| `title` | the option label (e.g. `Color`) | direct |
| `is_exclusive` | none — the exclusive/global option semantics are a Ceto decision | gap |
| `product` | none — intentionally omitted back-reference: the option is already embedded in its owning product, so re-embedding it would recurse; stays `None` | gap |
| `values` | the option's value projections (below) — published variants' values only | derived |
| `metadata` | none — no option metadata surface | gap |
| `created_at`, `updated_at` | the owning `Item` record's `creation` / `modified` (Recorded Decision 8) | direct |
| `deleted_at` | none — options delete with their product | gap |

| Medusa `StoreProductOptionValue` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | `optval_` + a hash of the family code, the attribute and the value (decision 7) | derived |
| `value` | the value label (e.g. `Red`) | direct |
| `rank` | none — no value-ranking source exists; stays `None` | gap |
| `option_id`, `option` | the owning option projection | derived |
| `metadata` | none — no value metadata surface | gap |
| `created_at`, `updated_at` | the owning `Item` record's `creation` / `modified` (Recorded Decision 8) | direct |
| `deleted_at` | none — values delete with their option | gap |

## Product Image → ERPNext `File` / `Item` image

| Medusa `StoreProductImage` field | Ceto/ERPNext source | Classification |
|---|---|---|
| `id` | `img_` + a hash of the item code (decision 7) | derived |
| `url` | the `Item` `image` URL — the only image source | direct |
| `rank` | none — no image-ranking source exists; stays `None` | gap |
| `metadata` | none — no image metadata surface | gap |
| `created_at`, `updated_at` | the owning `Item` record's `creation` / `modified` (Recorded Decision 8) | direct |
| `deleted_at` | none — images delete with their product | gap |

## Auth and error semantics

Shared with the whole Store read surface — recorded once in
[products-endpoints.md](./products-endpoints.md): publishable-key-only
guest reads (`401 unauthorized`), strict extra-forbid query validation and
out-of-bounds pagination (`400 invalid_data`), and masked `404 not_found`
for unknown or unpublished ids.
