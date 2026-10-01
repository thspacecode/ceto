# Store Cart Endpoints — Source of Truth

Phase 0 pinned a machine-readable contract manifest that later phases
implement against. **Phase 1 implemented routes 1–3, Phase 2 implemented
routes 4–6** (line items), **Phase 3 implemented route 14** (customer
claim/transfer) and **Phase 4 implemented routes 7–9 and 13** (shipping
methods, promotions and taxes); the remaining routes are unimplemented.
**Phase 5 (chunk 1) pinned routes 10–12** (the loyalty gift-card and
store-credit contracts) and added the Ceto-owned ledger records they will
apply; the routes themselves are still unimplemented.

## Manifest

- Module: `ceto/types/http/store/carts/manifest.py`
- Tests: `ceto/tests/types/http/store/test_carts_manifest.py`
- API source (pinned): <https://docs.medusajs.com/api/store#carts>
- JS SDK (pinned): `@medusajs/js-sdk@2.21.1`
- Loyalty plugin (pinned): `@zjedene-medusa/loyalty-plugin@2.16.2` — the
  source of the `gift-cards` and `store-credits` route contracts, which the
  core `@medusajs/types` package does not publish payloads for

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
| 7. `POST /store/carts/{id}/shipping-methods` | implemented (Phase 4) | `{cart: StoreCart}` |
| 13. `POST /store/carts/{id}/taxes` | implemented (Phase 4) | `{cart: StoreCart}` |
| 14. `POST /store/carts/{id}/customer` | implemented (Phase 3) | `{cart: StoreCart}` |

### Shipping methods (Phase 4)

- **Add/replace** (`StoreAddCartShippingMethods`): `{option_id, data?}`.
  `option_id` must resolve to an **enabled** ERPNext `Shipping Rule` with
  `shipping_rule_type: "Selling"` that belongs to the cart's company;
  anything else (unknown, disabled, buying-side, foreign company) is
  `400 invalid_data`, as is a rule ERPNext itself rejects on save — notably
  a shipping-address country outside the rule's `countries` list
  (`ShippingRule.validate_countries`). With no shipping address ERPNext
  skips the country check, exactly as on Desk.
- Applying runs inside the cart row lock with the publishable-key scope
  guard evaluated **after the lock and before any mutation** (same order as
  every other mutation route), and the Quotation saves through the ERPNext
  controllers, so the charge row, its amount and the totals are always
  ERPNext's own output.
- **Replacement**: the Quotation carries a single `shipping_rule` link, so a
  new `option_id` replaces the applied one. Rules sharing account and cost
  center rewrite the single `Actual` charge row in place; a rule with a
  different account/cost center first drops the previous rule's charge row
  (matched the way `SellingController.remove_shipping_charge` matches it) so
  shipping is never counted twice.
- **`data` is accepted but never persisted**: Ceto's compatibility field for
  a cart shipping method is the Quotation's `Shipping Rule` link, which
  carries no provider payload, so there is nothing to store it in. The value
  is validated (must be an object) and dropped; a route test pins this.
- An **itemless** cart keeps the option link but, while it has no lines,
  reports no shipping method: ERPNext skips `calculate_taxes_and_totals` —
  and with it the rule application — for itemless documents, so no charge
  row exists and the charge materializes on the next save that has lines. A
  cart that drops its **last** line after a charge row existed keeps that
  row — the empty-cart baseline zeroes its amount — and therefore still
  reports the method with amount 0 instead of the stale rule amount. The
  response stays honest about the ERPNext state instead of inventing an
  amount.
- Cart totals reconcile under Medusa semantics: the `Actual` shipping row is
  a **charge, not item tax**, so its amount is carved out of `tax_total`,
  `item_tax_total`, `original_tax_total` and the per-line tax allocations,
  while `subtotal` is the item subtotal plus the shipping subtotal and
  `total` stays `grand_total` (`total + discount_total == subtotal +
  tax_total` on ERPNext's own numbers).
- **Single-object request**: the pinned `StoreAddCartShippingMethods` allows
  a single `{option_id, data?}` object or an array of them; Ceto supports
  the **single-object** form only. The Quotation carries exactly one
  `shipping_rule` link (ERPNext's native model), so a multi-method body has
  no target — non-object request bodies are rejected as `400` before
  payload validation.
- **Provider seam**: the rate source is ERPNext `Shipping Rule` masters,
  applied and priced by ERPNext's own controllers. **Shipgi** — the
  shipment-gateway app that owns provider integrations — is currently a
  skeleton with **no rate API**; it is the future seam for dynamic provider
  rates and, with it, a shipping-options listing route. Phase 4 therefore
  has no listing route: the public option id is the `Shipping Rule` name.

### Cart taxes (Phase 4)

- **Calculate** (`StoreCalculateCartTaxes`): the pinned request body is
  **empty** — any extra field is `400 invalid_data`.
- The request runs inside the cart row lock with the publishable-key scope
  guard evaluated **after the lock and before any mutation** (same order as
  every other mutation route), then recalculates through ERPNext's own
  `calculate_taxes_and_totals` (Shipping Rule application included) and saves
  through the shared cart save helper (`ceto/services/carts/taxes.py`).
- **Idempotent**: ERPNext recomputes every summary field from the rows, so
  repeating the request reproduces the same numbers and never duplicates a
  charge or template row. An **itemless** cart keeps the empty-cart baseline
  (ERPNext skips the calculation for documents without lines).
- **Configuration changes reload stale templates**: when a region/sales-channel
  change resolves to a different `Sales Taxes and Charges Template`, the taxes
  rows are reloaded with ERPNext's `get_taxes_and_charges` instead of being
  left on the previous template (ERPNext only fills an *empty* taxes table on
  its own). The same template keeps its rows untouched, and the selected
  Shipping Rule survives a reload — its `Actual` charge row is recreated by
  the controller save, exactly once. Missing or disabled templates reject the
  request as `400 invalid_data` before any row is touched; deeper controller
  validation maps through the router and rolls the transaction back.

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

### Loyalty routes: gift cards and store credits (Phase 5, chunk 1)

- The three routes are **not** core Medusa: the loyalty plugin owns them and
  the manifest pins its release together with the core SDK/types pins. The
  corrected contracts, verified against `@zjedene-medusa/loyalty-plugin@2.16.2`:
  - `POST /store/carts/{id}/gift-cards` — body `{code}` in a strict object
    (`StoreAddGiftCardToCart`); optional cart session, like the other cart
    mutations.
  - `DELETE /store/carts/{id}/gift-cards` — **bodyful**: `{code}`
    (`StoreRemoveGiftCardFromCart`). The earlier "empty body" reading was
    wrong; the removal mirrors the plugin's strict `{code}` validator.
  - `POST /store/carts/{id}/store-credits` — body `{amount?}`
    (`StoreAddStoreCreditsToCart`). The plugin middleware authenticates the
    customer (session or bearer), so the route — unlike the gift-card routes
    — requires an authenticated customer. The plugin validator is a lenient
    `z.object` (unknown fields stripped), and Ceto mirrors that; a provided
    amount must be positive. When omitted, the plugin reserves the whole
    available balance.
- The plugin serializes applied gift cards as `gift_cards: [{code}]` on the
  cart and models both kinds of cart credit as core `credit_lines`
  (`CartCreditLineDTO`: `id`, `cart_id`, `amount`, `reference`
  (`gift-card` / `store-credit`), `reference_id`, `metadata`, timestamps).
  `StoreCart` now carries both collections; gift-card codes are stored
  hash-only with a display hint, so the serialized `code` is the hint and
  clients remove an applied gift card by resubmitting the original code.
- Ceto-owned records behind the routes: `Ceto Credit Wallet` (the
  provider-backed gift-card / store-credit ledger) and `Ceto Cart Credit
  Reservation` (one hold on a wallet per cart Quotation). See
  `docs/carts/core-cart.md` for the invariants.

### Publishable-key scoping on mutations

Every mutating route validates the key scope through a `guard` callback that
`CartService` invokes against the **row-locked** cart reference *before* any
Quotation change is applied. A wrong-scoped key therefore causes `403
not_allowed` with **no mutation** (no quantity change, no row removal, no
mapping deletion), and the inside-lock check cannot be raced between check and
save (no TOCTOU).
