# Core cart configuration (Phase 1 + Phase 2 line items)

Ceto stores each open cart as a draft ERPNext `Quotation` with
`order_type = "Shopping Cart"`. A lightweight `Ceto Cart Reference` record
holds only the public Medusa ID, access ownership, region/channel IDs, locale,
and metadata. It is not a second cart aggregate.

Configure cart defaults in the site's private `site_config.json` under
`ceto_cart`:

```json
{
  "ceto_cart": {
    "guest_customer": "Webshop Guest",
    "company": "Example Company",
    "selling_price_list": "Standard Selling",
    "currency": "USD",
    "territory": "All Territories",
    "default_region_id": "reg_us",
    "default_sales_channel_id": "sc_web",
    "valid_for_days": 30,
    "publishable_keys": {
      "pk_example": {
        "region_id": "reg_us",
        "sales_channel_id": "sc_web"
      }
    },
    "regions": {
      "reg_us": {
        "company": "Example Company",
        "selling_price_list": "Standard Selling",
        "currency": "USD",
        "territory": "All Territories"
      }
    },
    "sales_channels": {
      "sc_web": {
        "selling_price_list": "Standard Selling"
      }
    }
  }
}
```

`guest_customer`, `company`, and `selling_price_list` are required after the
selected region and sales-channel overlays are applied. Currency defaults to
the selected Price List currency. If `regions` or `sales_channels` is present,
unknown IDs are rejected.

Every cart request must send `x-publishable-api-key`. A key's optional region
and sales-channel scope supplies create defaults and prevents cross-scope cart
access. Keep real key values in private site configuration; do not commit them.

Guest access is capability-based: possession of the cryptographically random
`cart_...` ID grants access while `owner_user` is empty. Carts created in an
authenticated session are restricted to that Frappe User. Mutations lock both
the reference and Quotation rows before validation and save.


## Phase 2: line items (implemented)

- Each cart line is a `Quotation Item` child row paired with a
  `Ceto Cart Line Item Reference` record that owns the stable public id
  (`li_` + 128 bits of crypto random), per-line metadata, and the link to the
  Quotation row. Rows are added/updated/deleted through `CartLineItems`, which
  always persists through ERPNext controllers.
- `variant_id` in add payloads maps directly to the enabled ERPNext Item code
  in Phase 2 (resolution isolated in `ceto/services/carts/variants.py` for a
  future variant provider); quantities must be positive integers.
- All rates, discounts, taxes and totals — including document-level totals —
  are produced by ERPNext (price list / pricing rules, taxes template); Ceto
  never derives totals itself. Empty carts keep a zeroed summary baseline
  because ERPNext skips recalculation for itemless documents.
- Cart saves go through the shared `CartLineItems.save` helper: the mandatory
  items check is relaxed only while the cart has no rows, never for carts with
  line items.
- Mutations lock the cart reference and Quotation rows (`SELECT … FOR UPDATE`)
  and validate the publishable-key scope inside that lock before mutating, so
  wrong-scoped keys cause no mutation and cannot race the check (no TOCTOU).


## Phase 4: shipping methods, promotions and taxes (implemented)

Phase 4 adds the shipping-methods and taxes routes plus promotions; the
shipping/taxes route behavior is documented in `docs/carts/endpoints.md`
(`ceto/services/carts/shipping.py`, `ceto/services/carts/taxes.py`). The
promotions behavior shares the phase and is recorded here.

- `POST /store/carts/{id}/promotions` and `DELETE /store/carts/{id}/promotions`
  map Medusa promotion codes onto ERPNext's native coupon model: a `Coupon
  Code` record linked to a `Pricing Rule`, stored on the Quotation through its
  single `coupon_code` link (see `ceto/services/carts/promotions.py`).
- ERPNext's document model natively supports exactly **one** coupon per
  transaction, and Ceto exposes exactly that capacity honestly: submitting two
  distinct codes in one request, or a second distinct code while one is
  already applied, is rejected with `invalid_data` (`400`) instead of silently
  dropping a code. Duplicate copies of the same code are collapsed.
- Application runs ERPNext's own checks (`validate_coupon_code`: validity
  window, maximum use) and lets the Quotation save/validate pipeline apply the
  linked pricing rule; Ceto never computes a discount. Removal drops the
  coupon link, zeroes the document-level additional discount fields and
  recalculates through the same controllers, so a removed coupon can never
  leave a lingering discount.
- `promo_codes` is also accepted on cart create (applied inside the same
  transaction) and cart update (Medusa replace semantics: an empty list clears
  the coupon, a single code replaces the current one).
- Applied promotions serialize as `promotions: [{id, code, is_automatic}]`
  derived from the linked `Coupon Code`; discount amounts surface only through
  the ERPNext-calculated cart/line money fields.
- Like every cart mutation, promotion mutations run under the existing cart
  reference + Quotation row locks, after the publishable-key scope guard.


## Phase 5: gift cards and store credits (implemented)

Phase 5 pins the loyalty-plugin route contracts (see
`docs/carts/endpoints.md`), adds the Ceto-owned records the routes apply and
maps the `gift-cards` / `store-credits` routes onto them
(`ceto/services/carts/credits.py`). No ERPNext Custom Fields exist and none
were added (Recorded Decision 8): the whole ledger is Ceto compatibility
layer.

- **`Ceto Credit Wallet`** is the provider-backed ledger account. One wallet
  holds the balance a loyalty provider backs for one `wallet_type` (`Gift
  Card` / `Store Credit`), `provider`, `company`, `customer`, `currency`
  triple. `credit_total` − `debit_total` is the `balance`; totals are
  provider-maintained and never negative.
- Gift-card codes are stored **hash-only**: `code_hash` (lowercase SHA-256
  hex) plus a masked `code_hint`; the plaintext code never reaches the
  database. Gift-card wallets must carry both. Store-credit wallets are owned
  by a customer or claimable by code (anonymous accounts exist in the pinned
  `store-credit-accounts/claim` surface).
- **Company is part of wallet uniqueness**: a code hash exists once per
  company, and a customer holds one store-credit wallet per company and
  currency — the same code or customer can hold separate wallets per company.
- **`Ceto Cart Credit Reservation`** is one credit-line hold: a public
  `credit_line_id` (the `StoreCartCreditLine.id`), the `wallet`, the cart
  `Quotation`, `currency`, a positive `amount`, and a `status`
  (`Reserved` / `Released` / `Consumed`). Reservations must match the
  Quotation's company and currency, may not point at a cancelled Quotation,
  and cannot outlive an expired wallet.
- **Reservation-aware balances**: every open `Reserved` reservation reduces
  what further reservations may hold; `Released` and `Consumed` stop
  counting. The wallet balance itself is untouched until completion debits it
  (Phase 6). Deleting a cart reference releases its reservations, the
  same cleanup contract the line-item references already follow.
- **Negative `Actual` accounting**: applying a hold books the reservation —
  the public credit line — and writes the applied amount as a negative
  `Actual` row on the Quotation taxes table, posted to the company's default
  receivable account. The deduction is an ordinary ERPNext tax row: the
  controllers fold it into `total_taxes_and_charges` and `grand_total`, so
  ERPNext stays the totals authority and no Ceto-computed total exists. The
  rows are recognizable without a marker field (`Actual`, receivable account,
  negative amount) and are always rebuilt — never patched — by the
  reconciliation.
- **Reconciliation under the cart lock**: after every totals-moving mutation
  `CartCredits.reconcile` re-caps the open holds (gift cards re-derive with
  the cart, store credits only shrink), releases valueless or
  foreign-denominated holds and rebuilds the deduction rows, healing
  tax-template reloads on the same save. Shrinking mutations unbook the
  deduction rows first, so the intermediate ERPNext save cannot reject a
  negative grand total: booked deductions can never drive `total` negative,
  and a fully-deducted cart totals exactly 0.
- **Serialized summary**: `gift_cards` reports the masked hints of the open
  gift-card holds; `credit_lines` reports every open hold (both kinds) in
  application order; `gift_card_total` sums the gift-card subset and
  `credit_line_total` all of them. The shipping charge and the negative
  deduction rows are carved out of the Medusa tax fields, so the serialized
  cart always satisfies
  `total + discount_total + credit_line_total == subtotal + tax_total`.

## Phase 6: cart completion (implemented)

Completion (`POST /store/carts/{id}/complete`,
`ceto/services/carts/completion.py`) turns the cart's draft Quotation into a
placed order inside one locked, atomic transaction. The route returns the
pinned `StoreCompleteCartResponse` union itself — no `{cart: …}` wrapper —
and the route-level behavior is documented in `docs/carts/endpoints.md`;
this section records the configuration and the ERPNext side.

- **Locking**: completion locks the cart reference row and then the
  Quotation row, the same order as every cart mutation
  (`CartAccess.lock_for_completion`). Unlike the mutation lock it tolerates a
  *submitted* Quotation, so the replay path can resolve the order an earlier
  completion booked; unknown carts, missing or cancelled Quotations and
  non-Shopping-Cart drafts stay masked as `404 not_found`.
- **Preflight refusals** leave the cart open and return the pinned
  `type: "cart"` member with a structured error instead of raising: empty
  cart, missing email, missing shipping address, missing shipping method,
  the optional stock check and the payment readiness gate, evaluated in that
  order so a provider is never asked to authorize a cart that cannot be
  placed anyway.
- **Payment readiness** (Recorded Decision 7) is **open by default**: with
  no provider hook registered, completion proceeds without a payment gate.
  A provider registers the `ceto_cart_payment_readiness` hook; each
  registered method receives `cart_id`, `quotation` and `idempotency_key`
  (any subset), `None` means "no opinion", and the first falsy verdict
  fails the completion closed before any money moves or any order is
  created. Hook calls are synchronous and run while the cart reference and
  Quotation rows are row-locked inside the completion transaction, so a
  registered method must be **local and bounded** — no network I/O, no
  awaited jobs, no unbounded reads. A slow or remote hook stalls every
  concurrent cart mutation of the same cart and stretches the open
  transaction; a provider that has to reach a gateway records its intent
  locally and answers asynchronously (a `None` verdict keeps the gate open
  until then).
- **Stock check** is **off by default**: `bench set-config ceto_cart_stock_check 1`
  enables it. Enabled, every stocked item row must have ERPNext projected
  stock (`Bin.projected_qty`) in its warehouse covering the cart quantity;
  non-stock items and rows without a warehouse are skipped, so the gate
  never fails a cart on missing master data.
- **Settle**: the Quotation's `valid_till` is refreshed when it has passed
  (Medusa carts never expire; the ERPNext validity artifact must not block
  an old cart), the Quotation is submitted, ERPNext's own mapper produces
  the submitted Sales Order with the cart's stored per-row pricing
  re-asserted (`ceto/services/carts/conversion.py`), every Sales Order row
  is asserted back onto a `Ceto Cart Line Item Reference` mapping of this
  cart (an ERPNext free-item row or any other unmapped row refuses the
  completion instead of silently disappearing from the order), the **Ceto
  Order Reference** is booked — the public `order_…` id, the Sales Order
  and the `cart_id`, unique on all three — and the wallets behind the
  cart's credit holds are debited (`CartCredits.consume_cart_credits`).
  Everything shares the caller's transaction inside the
  `ceto_cart_completion_settle` savepoint: an expected Frappe/ERPNext
  validation failure (`frappe.ValidationError` and its subclasses — the
  business-validation family ERPNext's controllers raise through
  `frappe.throw`) is rolled back to the savepoint — submission, Sales
  Order, reference and wallet debits — while the cart row lock stays held,
  and is returned as the pinned refusal `OrderPlacementError` (type
  `order_placement_error`) for the untouched open cart, retry-ready.
  Anything wider (a programming or infrastructure fault) is deliberately
  not caught: it propagates to the router and surfaces as `500
  internal_error` with the full request rollback.
- **Replay**: a completed cart's Quotation has left the draft state every
  cart route requires, so the order reference — resolved by the unique
  `cart_id` — is the only way back. Every repeat of the complete route
  re-serializes the same placed order; the rest of the cart surface masks
  the cart as `404 not_found`.
