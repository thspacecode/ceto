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
   `Item Group` node descends from one of the configured storefront root
   `Item Group` nodes; nothing outside the roots is ever visible — an
   unpublished or unknown id masks as `404 not_found`, never a `500`. The
   roots live in site configuration (decided per deployment), not in code.
2. **Collections are Ceto-stored catalog records.** No ERPNext master owns
   a collection, so Ceto owns the storage: `handle` is unique and stored,
   `id` is minted (`pcol_…`-style) rather than an ERPNext record name. The
   storage DocType and its fixtures belong to a behavior slice — this
   contract slice ships none.
3. **Product types carry minted ids.** ERPNext has no product-type master
   either, so the types are Ceto-curated catalog records: the `value` is
   the curated label, the `id` is minted. The ERPNext projection (how an
   `Item` references its type) is decided with the products behavior
   slice.
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
7. **Bootstrap fixtures are approved later.** Demo collections and types
   (and demo `Item Group` overlays) are approved with the behavior slices
   that own the storage, never in this contract slice.
8. **Record timestamps are never fabricated.** Categories serve the real
   `Item Group` `creation` / `modified`; collections and types serve their
   record timestamps once the storage slice lands; until then the columns
   stay `None` (the pinned contract keeps every timestamp optional).

## Collection → Ceto catalog storage

| Medusa `StoreCollection` field | Ceto catalog record | Classification |
|---|---|---|
| `id` | minted public id (`pcol_…`-style) of the stored collection (Recorded Decision 2) | derived |
| `title` | the stored collection title | direct |
| `handle` | the stored unique handle (uniqueness enforced by Ceto storage) | direct |
| `metadata` | none — the catalog record carries no metadata surface | gap |
| `external_id` | none — no external system assigns collection ids | gap |
| `created_at`, `updated_at` | record `creation` / `modified` once the storage slice lands (Recorded Decision 8) | direct |
| `deleted_at` | none — Ceto deletes collections hard; no soft-delete tombstone | gap |
| `products` | dropped from the projection model entirely — membership deferred (Recorded Decision 4) | gap |

The pinned `BaseCollection` marks `created_at`, `updated_at` and
`deleted_at` non-nullable; as with currencies, the pinned store list serves
a field-selected subset and Ceto keeps every such column optional in the
contract, omitting what has no honest source yet.

## Product Category → ERPNext `Item Group`

| Medusa `StoreProductCategory` field | ERPNext `Item Group` source | Classification |
|---|---|---|
| `id` | stable public id of the published `Item Group` node; minting decided with the behavior slice | derived |
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

Publication boundary: only nodes descending from a configured storefront
root are served (Recorded Decision 1). The pinned store type already omits
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
| `id` | minted public id of the curated type (Recorded Decision 3) | derived |
| `value` | the curated type label stored on the catalog record | direct |
| `external_id` | none — no external system assigns type ids | gap |
| `metadata` | none — the catalog record carries no metadata surface | gap |
| `created_at`, `updated_at` | record `creation` / `modified` once the storage slice lands (Recorded Decision 8) | direct |
| `deleted_at` | none — Ceto deletes types hard; no soft-delete tombstone | gap |

How a published `Item` references its type is a products-slice decision
(Recorded Decision 3); this slice pins only the served shape.

## Auth and error semantics

Shared with the whole Store read surface — recorded once in
`docs/catalog/endpoints.md`: publishable-key-only guest reads (`401
unauthorized`), strict extra-forbid query validation and out-of-bounds
pagination (`400 invalid_data`), and masked `404 not_found` for unknown or
unpublished ids.
