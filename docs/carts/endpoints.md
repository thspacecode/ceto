# Store Cart Endpoints — Source of Truth

Phase 0 pinned a machine-readable contract manifest that later phases
implement against. **Phase 1 implemented routes 1–3, Phase 2 implemented
routes 4–6** (line items), **Phase 3 implemented route 14** (customer
claim/transfer) and **Phase 4 implemented routes 8–9** (promotions); the
remaining routes are unimplemented.

## Manifest

- Module: `ceto/types/http/store/carts/manifest.py`
- Tests: `ceto/tests/types/http/store/test_carts_manifest.py`
- API source (pinned): <https://docs.medusajs.com/api/store#carts>
- JS SDK (pinned): `@medusajs/js-sdk@2.21.1`

The manifest is pure Python (`dataclass` entries, no Frappe imports) so it can
be consumed by request validation codegen and tested standalone.

## Pinned routes (15)

| # | Method | Path | Request type | Response type | Auth | SDK method |
|---|--------|------|--------------|---------------|------|------------|
| 1 | GET | `/store/carts/{id}` | — | `StoreCartResponse` | publishable-key | `retrieve` |
| 2 | POST | `/store/carts` | `StoreCreateCart` | `StoreCartResponse` | pk + optional session | `create` |
| 3 | POST | `/store/carts/{id}` | `StoreUpdateCart` | `StoreCartResponse` | pk + optional session | `update` |
| 4 | POST | `/store/carts/{id}/line-items` | `StoreAddCartLineItem` | `StoreCartResponse` | pk + optional session | `createLineItem` |
| 5 | POST | `/store/carts/{id}/line-items/{line_id}` | `StoreUpdateCartLineItem` | `StoreCartResponse` | pk + optional session | `updateLineItem` |
| 6 | DELETE | `/store/carts/{id}/line-items/{line_id}` | — | `StoreLineItemDeleteResponse` | pk + optional session | `deleteLineItem` |
| 7 | POST | `/store/carts/{id}/shipping-methods` | `StoreAddCartShippingMethod` | `StoreCartResponse` | pk + optional session | `addShippingMethod` |
| 8 | POST | `/store/carts/{id}/promotions` | `StoreCartAddPromotion` | `StoreCartResponse` | pk + optional session | `addPromotions` |
| 9 | DELETE | `/store/carts/{id}/promotions` | `StoreCartRemovePromotion` | `StoreCartResponse` | pk + optional session | `removePromotions` |
| 10 | POST | `/store/carts/{id}/gift-cards` | `StoreAddCartGiftCards` | `StoreCartResponse` | pk + optional session | — |
| 11 | DELETE | `/store/carts/{id}/gift-cards` | — | `StoreCartResponse` | pk + optional session | — |
| 12 | POST | `/store/carts/{id}/store-credits` | `StoreAddCartStoreCredits` | `StoreCartResponse` | pk + optional session | — |
| 13 | POST | `/store/carts/{id}/taxes` | `StoreCalculateCartTaxes` | `StoreCartResponse` | pk + optional session | — |
| 14 | POST | `/store/carts/{id}/customer` | — | `StoreCartResponse` | pk + customer session | `transferCart` |
| 15 | POST | `/store/carts/{id}/complete` | — | `StoreCompleteCartResponse` | pk + optional session | `complete` |

## Source of truth vs. SDK compatibility

The **API reference URL** is the source of truth for route shape, request and
response types. The **JS SDK** is a compatibility layer only:

- `@medusajs/js-sdk@2.21.1` directly supports the 11 cart methods
  `create`, `retrieve`, `update`, `createLineItem`, `updateLineItem`,
  `deleteLineItem`, `addShippingMethod`, `addPromotions`, `removePromotions`,
  `complete`, and `transferCart` (which maps to `POST /store/carts/{id}/customer`).
- The SDK has **no** direct method for the `taxes`, `gift-cards` and
  `store-credits` routes (4 route entries in the manifest carry
  `sdk_method = None`). Those routes must be called with a raw HTTP client when
  replicating Medusa client behavior.

When Medusa ships a new version, update `CART_API_SOURCE_URL`,
`CART_SDK_VERSION` and the manifest entries together, then fix the tests —
they intentionally fail on drift.


## Implemented routes (Phase 1 + Phase 2 + Phase 3)

Handler module: `ceto/api/store/carts.py`. All cart routes are guest-enabled
and require the `x-publishable-api-key` header.

| Route | Status | Response shape |
|---|---|---|
| 1. `GET /store/carts/{id}` | implemented (Phase 1) | `{cart: StoreCart}` |
| 2. `POST /store/carts` | implemented (Phase 1) | `{cart: StoreCart}` |
| 3. `POST /store/carts/{id}` | implemented (Phase 1) | `{cart: StoreCart}` |
| 4. `POST /store/carts/{id}/line-items` | implemented (Phase 2) | `{cart: StoreCart}` |
| 5. `POST /store/carts/{id}/line-items/{line_id}` | implemented (Phase 2) | `{cart: StoreCart}` |
| 6. `DELETE /store/carts/{id}/line-items/{line_id}` | implemented (Phase 2) | `{id, object: "line-item", deleted: true, parent}` |
| 14. `POST /store/carts/{id}/customer` | implemented (Phase 3) | `{cart: StoreCart}` |

### Customer claim / transfer (Phase 3)

- **Claim** (`SDK: transferCart`): `POST /store/carts/{id}/customer` with an
  empty body and a publishable key. Requires an **authenticated session** —
  a guest request gets `401 unauthorized`, as does an authenticated Frappe
  User with no Customer linked through its `Contact` (resolver:
  `ceto/services/carts/customers.py`).
- The claim runs inside the cart row lock (same lock order as every other
  mutation, with the publishable-key scope guard evaluated inside the lock):
  the session user resolves to its ERPNext Customer, the guest party,
  contact and address context is replaced, item pricing is re-fetched by
  ERPNext for the new customer (pricing rules) while the
  **sales-channel price list stays configured** — it is never re-inferred
  from the claiming Customer's default (Recorded Decision 1) — taxes/totals
  are recalculated by the controller, and `owner_user` / `owner_customer`
  persist on the `Ceto Cart Reference`.
- Cart-scoped temporary addresses captured under the guest Customer are
  **copied to customer-owned Addresses** (Recorded Decision 4): each still
  attached temporary is cloned as an Address linked only to the claiming
  Customer, the billing/shipping slots are relinked to the copy (one shared
  copy when both slots reference the same temporary) and the temporary is
  deleted. Addresses already linked to the claiming Customer stay attached
  unchanged; nothing else is ever attached to the claiming Customer.
- Claiming a cart owned by a different user is masked as `404 not_found`;
  claiming again as the same user is idempotent (no mutation).

### Line-item endpoints (Phase 2)

- **Add** (`StoreAddCartLineItem`): `{variant_id, quantity, metadata?}`.
  `quantity` must be a positive integer; `variant_id` must resolve to an
  enabled ERPNext Item (Phase 2: public variant id **is** the Item code).
  Adding an already-present variant merges quantities into the existing line,
  which keeps its stable `li_…` id and metadata. Returns `{cart: …}`.
- **Update** (`StoreUpdateCartLineItem`): `{quantity?, metadata?}`. Quantity
  must stay positive. Metadata follows cart metadata merge semantics: values
  are merged per key, `null` values remove a key, and an explicit
  `metadata: null` clears all keys. Returns `{cart: …}`.
- **Delete**: returns **exactly** `{id, object: "line-item", deleted: true,
  parent: <cart_id>}` with no `cart` wrapper. Unknown or foreign line ids are
  masked as `404 not_found` (including lines belonging to another cart). An
  emptied cart survives and stays mutable.
- The `fields` query parameter behaves as on the other cart routes for add and
  update; delete ignores it (fixed response shape).
- Errors use the shared Medusa translation (`invalid_data`, `unauthorized`,
  `not_allowed`, `not_found`).

### Publishable-key scoping on mutations

Every mutating route validates the key scope through a `guard` callback that
`CartService` invokes against the **row-locked** cart reference *before* any
Quotation change is applied. A wrong-scoped key therefore causes `403
not_allowed` with **no mutation** (no quantity change, no row removal, no
mapping deletion), and the inside-lock check cannot be raced between check and
save (no TOCTOU).
