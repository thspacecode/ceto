# Store Catalog Taxonomy — Medusa → Ceto/ERPNext Field Mapping (Phase 2 slice 2A)

Classification legend for every mapping row (same convention as
`docs/reference-data/field-mapping.md`):

- **direct** — the Medusa field maps 1:1 onto a stored Ceto catalog record
  field or an ERPNext/Frappe record field (possibly with type coercion).
- **derived** — the Medusa field is computed from Ceto configuration or
  ERPNext/Frappe records.
- **gap** — no Ceto/ERPNext equivalent exists; the field is omitted (the
  pinned contract permits it) and never fabricated.

Sources: pinned `@medusajs/types@2.21.1` (`http/collection/store`,
`http/product-category/store`, `http/product-tag/store`,
`http/product-type/store`) and `@medusajs/js-sdk@2.21.1` (see
`docs/catalog/endpoints.md`).

## Recorded decisions

1. **Categories are the ERPNext `Item Group` tree, published only inside
   the configured storefront roots.** A category is servable only when its
   `Item Group` node is a configured storefront root or descends from one;
   nothing outside the roots is ever visible — an unpublished or unknown id
   masks as `404 not_found`, never a `500`. The roots live in the
   `ceto_catalog.category_roots` site configuration (decided per
   deployment), not in code; with no configuration nothing is published —
   the routes serve an empty page rather than the ERPNext default tree.
2. **Collections are Ceto-stored catalog records.** No ERPNext master owns
   a collection, so Ceto owns the storage: the `Ceto Collection` DocType
   stores the unique `handle`, the `title`, the minted `pcol_…` public id
   (`pcol_` + 32 lowercase hex, minted by `ceto.services.catalog`), an
   optional `external_id` and an optional canonical JSON `metadata` object.
   The storage DocType ships with the Phase 2 slice 2B behavior slice.
3. **Product types carry minted ids.** ERPNext has no product-type master
   either, so the types are Ceto-curated catalog records: the `value` is
   the curated label and the unique business key of the `Ceto Product Type`
   DocType, the `id` is minted (`ptyp_` + 32 lowercase hex), and the record
   carries an optional `external_id` and an optional canonical JSON
   `metadata` object. The ERPNext projection (how an `Item` references its
   type) is decided with the products behavior slice.
4. **Collection-item membership is deferred.** The pinned `products`
   relation is dropped from the projection model entirely — no product
   contract exists in Ceto yet to embed — and returns with the catalog
   products slice.
5. **Tree filters are initially unsupported.** The category projection is
   flat: `parent_category` / `category_children` default to the empty
   tree, and `include_descendants_tree` / `include_ancestors_tree` are
   refused as unknown query keys (`docs/catalog/endpoints.md`).
6. **Ordering is deterministic everywhere:** collections by creation
   descending (the upstream validator's own default sort), categories by
   `lft` — the `Item Group` tree order — tags and types by `value`
   ascending.
7. **Bootstrap fixtures ship with the storage slices that own them.** The
   demo collections and product types are seeded by the development
   bootstrap's `SetupCatalog` step (`ceto.data.bootstrap_dev`), located by
   their stable business keys (collection `handle`, type `value`) with the
   public ids minted once at creation. The demo `Item Group` overlay ships
   with the category slice: `Dev Graphic Tees` extends the demo `Dev *`
   tree to a third level under `Dev Apparel > Dev T-Shirts`, seeded by
   `SetupItemGroups`; the bootstrap never writes site configuration, so the
   demo tree stays unservable until the deployment names its storefront
   roots in `ceto_catalog.category_roots` (the bootstrap README records the
   demo snippet).
8. **Record timestamps are never fabricated.** Categories serve the real
   `Item Group` `creation` / `modified`; the Ceto-stored collections and
   types serve their record `creation` / `modified` as-is since the slice
   2B storage landed; tags serve no timestamps of their own (a tag is a
   projection of other records' tags). The contract keeps every timestamp
   optional either way.

## Collection → Ceto catalog storage

| Medusa `StoreCollection` field | Ceto catalog record | Classification |
|---|---|---|
| `id` | minted public id (`pcol_` + 32 lowercase hex) of the stored collection; named by the `Ceto Collection` record (Recorded Decision 2) | derived |
| `title` | the stored collection `title` on the `Ceto Collection` record | direct |
| `handle` | the stored unique `handle` (uniqueness enforced by Ceto storage) | direct |
| `metadata` | the stored optional canonical JSON `metadata` object on the record | direct |
| `external_id` | the stored optional `external_id` on the record — carried verbatim, never resolved by | direct |
| `created_at`, `updated_at` | the record's `creation` / `modified`, served as-is (Recorded Decision 8) | direct |
| `deleted_at` | none — Ceto deletes collections hard; no soft-delete tombstone | gap |
| `products` | dropped from the projection model entirely — membership deferred (Recorded Decision 4) | gap |

The pinned `BaseCollection` marks `created_at`, `updated_at` and
`deleted_at` non-nullable; as with currencies, the pinned store list serves
a field-selected subset and Ceto keeps every such column optional in the
contract while the storage serves the real record timestamps.

## Product Category → ERPNext `Item Group`

| Medusa `StoreProductCategory` field | ERPNext `Item Group` source | Classification |
|---|---|---|
| `id` | stable public id of the published `Item Group` node — `pcat_` + 32 lowercase hex derived deterministically (SHA-256 truncation) from the node name, so the id is stable and addressable with no core schema change | derived |
| `name` | `item_group_name` | direct |
| `handle` | slug of `item_group_name` (the node's stable URL segment) | derived |
| `description` | none — `Item Group` carries no description; never fabricated | gap |
| `rank` | none — no sibling-ranking source exists; stays `None` | gap |
| `parent_category_id` | the public id of `parent_item_group` when the parent is published, else `None` | derived |
| `parent_category` | the embedded parent projection — empty tree until the tree decision lands (Recorded Decision 5) | derived |
| `category_children` | the embedded child projections — empty list until the tree decision lands (Recorded Decision 5) | derived |
| `external_id` | none — no external system assigns category ids | gap |
| `metadata` | none — the config schema has no category metadata | gap |
| `created_at`, `updated_at` | `creation` / `modified` of the `Item Group` record — real record timestamps (Recorded Decision 8) | direct |
| `deleted_at` | none — ERPNext deletes `Item Group` nodes hard | gap |

Publication boundary: only nodes that are a configured storefront root or
descend from one are served (Recorded Decision 1, resolved through
`ceto.config.catalog`). The pinned store type already omits
`is_active` / `is_internal` — publication is Ceto's projection decision,
never a served flag — and group-ness (`is_group`) is invisible on the
store surface: any published node is a category.

## Product Tag → Frappe user tags

| Medusa `StoreProductTag` field | Frappe source | Classification |
|---|---|---|
| `id` | stable public tag id; minting decided with the tags behavior slice | derived |
| `value` | the deduplicated user-tag strings of the published catalog items | direct |
| `external_id` | none — no external system assigns tag ids | gap |
| `metadata` | none — tags carry no metadata surface | gap |
| `created_at`, `updated_at` | none — a tag is a projection of other records' tags, with no timestamps of its own (Recorded Decision 8) | gap |
| `deleted_at` | none — a tag disappears with its last reference; no tombstone | gap |

The list serves each distinct value once, ordered by `value` (Recorded
Decision 6). Tag fixtures are approved with the behavior slices (Recorded
Decision 7).

## Product Type → Ceto catalog storage

| Medusa `StoreProductType` field | Ceto catalog record | Classification |
|---|---|---|
| `id` | minted public id (`ptyp_` + 32 lowercase hex) of the curated type; named by the `Ceto Product Type` record (Recorded Decision 3) | derived |
| `value` | the curated type label stored as the record's unique `value` | direct |
| `external_id` | the stored optional `external_id` on the record — carried verbatim, never resolved by | direct |
| `metadata` | the stored optional canonical JSON `metadata` object on the record | direct |
| `created_at`, `updated_at` | the record's `creation` / `modified`, served as-is (Recorded Decision 8) | direct |
| `deleted_at` | none — Ceto deletes types hard; no soft-delete tombstone | gap |

How a published `Item` references its type is a products-slice decision
(Recorded Decision 3); this slice pins only the served shape.

## Auth and error semantics

Shared with the whole Store read surface — recorded once in
`docs/catalog/endpoints.md`: publishable-key-only guest reads (`401
unauthorized`), strict extra-forbid query validation and out-of-bounds
pagination (`400 invalid_data`), and masked `404 not_found` for unknown or
unpublished ids.
