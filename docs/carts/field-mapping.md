# Store Carts — Medusa → ERPNext Field Mapping (Phase 0)

Classification legend for every mapping row:

- **direct** — the Medusa field maps 1:1 onto an ERPNext field (possibly with
  type coercion).
- **derived** — the ERPNext field is computed from one or more Medusa fields
  or Ceto configuration.
- **gap** — no ERPNext equivalent exists; handled by a Ceto compatibility
  layer (Ceto doctypes / behavior), **not** by Custom Fields on core ERPNext
  doctypes. Phase 0 records the gap only.

## Cart → Quotation

| Medusa `StoreCart` field | ERPNext `Quotation` field | Classification |
|---|---|---|
| `id` (`cart_…`) | Ceto external-identity record linked to `Quotation.name` | gap |
| `region_id` | `company` (via Ceto region → Company map) | derived |
| `sales_channel_id` | `selling_price_list` / Warehouse / Territory / Cost Center (via Ceto sales-channel config) | derived |
| `currency_code` | `currency` (must match the price list currency) | derived |
| `customer_id` | `party_name` (Customer; configured Guest Customer when unset) | direct/derived |
| `email` | `contact_email` | direct |
| `shipping_address` / `billing_address` | `shipping_address_name` / `customer_address` (cart-scoped temporary Address) | direct |
| `subtotal`, `original_subtotal` | item subtotal (`net_total` / `total`) **+ shipping subtotal** (Medusa reconciliation) | derived |
| `discount_total`, `discount_subtotal` | `additional_discount_percentage` / pricing-rule discounts | derived |
| `shipping_total` | Shipping Rule charge row | derived |
| `tax_total`, `item_tax_total`, `original_tax_total` | tax rows minus the Shipping Rule charge row and the negative credit deduction rows (both are `Actual` charges, not item tax) | derived |
| `total` | `grand_total` (must reconcile after recalculation; `total + discount_total + credit_line_total == subtotal + tax_total`) | derived |
| `gift_cards[].code` | open gift-card holds serialized as the wallet's masked `code_hint` (codes stored hash-only) | derived |
| `gift_card_total` | sum of the cart's open gift-card credit lines | derived |
| `credit_lines[]`, `credit_line_total` | open `Ceto Cart Credit Reservation` holds (gift card and store credit) and their amount sum | gap |
| `completed_at` | trigger for Sales Order submission (see Completion) | gap |
| `metadata` | Ceto Cart Metadata child/mapping doctype | gap |
| `item_tax_mode`, exact `sales_channel_id` | no ERPNext equivalent | gap |

## Line Item → Quotation Item

| Medusa `StoreCartLineItem` field | ERPNext `Quotation Item` field | Classification |
|---|---|---|
| `id` (`li_…`) | `Ceto Cart Line Item Reference` record linking the line id to the Quotation Item row | gap |
| `product_variant_id` | `item_code` (public variant provider → Item) | derived |
| `title`, `product_title`, `variant_title` | `item_name` / `description` | direct |
| `thumbnail` | `image` | direct |
| `quantity` | `qty` | direct |
| `unit_price` | `rate` (from price list / pricing rule) | derived |
| `compare_at_unit_price` | no direct field; drives strikethrough display pricing | gap |
| `subtotal`, `total`, `discount_total`, `tax_total` | `amount` / `net_rate`, tax rows (recomputed) | derived |
| `requires_shipping` | toggles whether the row drives the Shipping Rule | derived |
| `is_discountable` | gates Pricing Rule application for the row | derived |
| `variant` (payload on add/update, `variant_id` option) | `item_code` resolution at add time | direct |
| gift-card / store-credit line adjustments | Ceto ledger rows, not Quotation Item | gap |

Phase 2 serialization notes:

- The public line `id` is `li_` + 128 bits of cryptographic random, mapped to the
  Quotation Item child-row `name` through `Ceto Cart Line Item Reference`; line
  metadata lives on that mapping record and follows the cart metadata merge
  semantics (null removes a key, explicit `metadata: null` clears all keys).
- The public variant id equals the enabled ERPNext Item code for now; resolution
  is isolated behind the variants module.
- Line money values are read straight from ERPNext row calculations:
  `unit_price` ← `net_rate` (fallback `rate`), `original_unit_price` ←
  `price_list_rate`, `subtotal` ← `net_amount`, `discount_total` ←
  `discount_amount`. Per-line `tax_total` is the ERPNext-calculated tax
  allocation for the row (from the Quotation's `item_wise_tax_details` child
  rows, with the legacy per-tax-row `item_wise_tax_detail` JSON as fallback),
  and `total` = `net_amount` + that allocation; no tax rate is ever invented
  in Ceto, so summing the line tax totals reconciles with the cart-level
  `item_tax_total` for supported percentage/template taxes.
- Adding an already-present variant merges quantities into the existing row
  (Medusa default); the existing line keeps its identity and metadata.
- Empty carts keep a zeroed baseline: ERPNext skips `calculate_taxes_and_totals`
  for itemless documents, so deleting the last line resets the Quotation summary
  fields instead of recomputing them.

## Address → Address

| Medusa `StoreCartAddress` field | ERPNext `Address` field | Classification |
|---|---|---|
| `first_name`, `last_name` | `address_title` (cart-scoped temp: `Cart <cart_id>`) | direct |
| `company` | suffix of `address_title` / Ceto mapping | direct |
| `address_1`, `address_2` | `address_line1`, `address_line2` | direct |
| `city`, `province`, `postal_code` | `city`, `state`, `pincode` | direct |
| `country_code` | `country` (resolve ISO code to ERPNext Country name) | derived |
| `phone` | `phone` | direct |
| `id` | `name` (Ceto temp address name, e.g. `CAR-Addr-…`) | derived |

Cart addresses are created as **cart-scoped temporary Addresses** linked to
the Quotation only, with no Customer link. On customer claim (transfer) or
cart completion, a customer-linked copy is created and the Quotation is
relinked to that copy; the claim copy is linked only to the claiming
Customer (one shared copy when billing and shipping reference the same
temporary) and the temporary is deleted, while addresses already owned by
the claiming Customer stay attached unchanged.

## Promotion → Pricing Rule + Coupon Code

| Medusa promotion field | ERPNext target | Classification |
|---|---|---|
| `promotions[].code` (applied) | `Coupon Code` linked to a `Pricing Rule` | direct |
| promotion `discount_total` share | Pricing Rule discount / discount amount | derived |
| `removePromotions` body (`promo_codes`) | Coupon Code removal + recalculation | direct |
| Medusa promotion types (free shipping, buy-X, fixed amount in region currency) | closest Pricing Rule discount type; unsupported types fall back to a Ceto-computed discount row | gap |

## Shipping Method → Shipping Rule + Taxes

| Medusa `StoreCartShippingMethod` field | ERPNext target | Classification |
|---|---|---|
| `shipping_option_id` | `shipping_rule` on the Quotation (the option id **is** the Shipping Rule name; enabled, `Selling`, cart company) | derived |
| `name` | Shipping Rule label (stamped into the charge row description) | direct |
| `amount` | `tax_amount` of the `Actual` charge row the controller wrote | direct |
| `subtotal`, `total` | the same row amount (no tax-on-shipping is produced) | derived |
| `tax_total` | always 0: the Selling taxes allocate no tax onto the charge row | derived |
| `is_tax_inclusive` | always false: the charge row carries no tax allocation, so its amount is tax-exclusive | derived |
| `created_at` / `updated_at` | `creation` / `modified` of the `Actual` charge row (the row is the method identity) | direct |
| `data` (request payload) | accepted but not persisted — no compatibility field exists on the rule link | gap |

The Phase 4 rate source is ERPNext `Shipping Rule` masters, priced and
applied by ERPNext's own controllers. **Shipgi** — the shipment-gateway app
that owns provider integrations — is currently a skeleton with no rate API;
it is the future seam for dynamic provider rates and a shipping-options
listing route (deliberately not built in Phase 4).

## Cart Credit (gift card / store credit) → Ceto Credit Wallet + Quotation tax row

The loyalty-plugin cart credits (Phase 5) map onto the Ceto-owned ledger, not
onto ERPNext master data (Recorded Decision 8):

| Medusa loyalty field | Ceto / ERPNext target | Classification |
|---|---|---|
| `POST …/gift-cards` body `code` | wallet lookup by SHA-256 `code_hash`, scoped to the cart's company; plaintext never stored | gap |
| `gift_cards[].code` (serialized) | wallet `code_hint` (masked); clients resubmit the original code to remove | derived |
| `credit_lines[].id` (`cl_…`) | `Ceto Cart Credit Reservation.credit_line_id` | gap |
| `credit_lines[].reference` (`gift-card` / `store-credit`) | wallet `wallet_type` | derived |
| `credit_lines[].reference_id` | `Ceto Credit Wallet` name | direct |
| `credit_lines[].amount` | reservation `amount`, re-capped by the reconciliation | derived |
| `credit_line_total`, `gift_card_total` | sum of open holds (all / gift-card subset) | derived |
| applied credit amount | negative `Actual` row on the Quotation taxes table, posted to the company's default receivable account | derived |
| removed / released hold | reservation `status = Released`; the deduction row is rebuilt and the totals restored | derived |

Accounting semantics (Phase 5):

- Applying a hold books the reservation and writes the applied amount as a
  **negative `Actual` row** on the taxes table. ERPNext's own controllers
  fold it into `total_taxes_and_charges` and `grand_total` — ERPNext stays
  the totals authority; Ceto never derives a total.
- The serializer carves the shipping charge **and** the deduction rows out of
  `tax_total`, `item_tax_total`, `original_tax_total` and the per-line tax
  allocations (cart charges, not item tax), while `total` keeps the deducted
  grand total. The deductions reappear as positive holds, so the summary
  always satisfies
  `total + discount_total + credit_line_total == subtotal + tax_total`.
- `CartCredits.reconcile` runs inside the cart lock after every
  totals-moving mutation: holds are re-capped to wallet availability and the
  remaining deductible amount (gift cards re-derive, store credits only
  shrink), valueless holds are released and the deduction rows are rebuilt —
  so a booked deduction can never drive `total` negative, and a
  tax-template reload heals on the same save. Shrinking mutations unbook the
  rows first so the intermediate ERPNext save stays valid.
- The wallet balance is untouched while the cart is open; completion debits
  it (Phase 6). Released holds stop counting and stop serializing.

## Tax Lines → Quotation taxes and charges

| Medusa tax line field | ERPNext target | Classification |
|---|---|---|
| `item_tax_line.rate_id` / description | Sales Taxes and Charges Template row | derived |
| `rate` | row `rate` (%) or `tax_amount` (absolute) | direct |
| `code`, `name` (provider tax code) | `account_head` resolution via Ceto tax-code map | derived |
| `shipping_tax_line` | shipping tax row | derived |
| Medusa per-item inclusive/exclusive modes (`item_tax_mode`) | `included_in_print_rate` handling | gap |

`POST /store/carts/{id}/taxes` (Phase 4) recalculates the cart through
ERPNext's own `calculate_taxes_and_totals` and save — no total is derived in
Ceto. Region/sales-channel changes that move `taxes_and_charges` reload the
rows with ERPNext's `get_taxes_and_charges` (ERPNext only fills an empty
taxes table), keep same-template rows untouched, and let the controller save
recreate the Shipping Rule charge row exactly once
(`ceto/services/carts/taxes.py`).

## Completion → Sales Order

| Medusa `StoreCompleteCartResponse` (`order`/`cart` union) | ERPNext target | Classification |
|---|---|---|
| `order` on success | Quotation → Sales Order (submit Quotation output, then submit Sales Order) | derived |
| `type: "cart"` (incomplete) | Quotation left open; completion error surfaced | gap |
| `payment_collection` requirement | Ceto requires payment readiness (authorized/captured per provider settings) **before** creating the Sales Order | gap |
| `order.id`, `order.display_id` | Ceto order-correlation record (Sales Order ↔ Medusa order id) | gap |
| payment status / credits | tracked in the provider ledger; cart credits consumed on completion | gap |

Phase 6 pins the completion contracts (the completion payload/response of the
carts types plus the `ceto/types/http/store/orders/` package), adds the
**Ceto Order Reference** record and implements the completion service
(`ceto/services/carts/completion.py`) that books it: the public
`order_…` id names the document, the linked Sales Order is the ERPNext
identity it stands for, and `cart_id` keeps the completed cart's public id
for the complete replay.

- `StoreOrder` mirrors the pinned `@medusajs/types@2.21.1` order for the
  columns the completion serializer can derive from the Sales Order and the
  cart's reference; the summary follows the cart reconciliation (shipping
  charge and consumed credit deductions carved out of the tax fields,
  `total` on the ERPNext grand total).
- `display_id` / `custom_display_id` are deliberately omitted (Recorded
  Decision 9), as are `version`, `summary`, `transactions`,
  `payment_collections`, `fulfillments` and `customer` until the matching
  provider exists. The pinned `item_discount_total` /
  `shipping_discount_total` split is omitted for the same reason of
  honesty: ERPNext carries a single order-level `discount_amount` (the
  coupon/additional discount; per-row pricing discounts ride the item
  rows) and gives the Shipping Rule charge no discount bucket, so the
  Medusa item/shipping discount split cannot be derived without inventing
  numbers — `discount_total` keeps the order-level amount.
- An order reference can only be born from a completed cart: its Quotation
  must be submitted. Submitted Quotations fail the draft check every cart
  route makes, so a completed cart is masked as `404 not_found` on the whole
  cart surface — the complete route replays by resolving the order reference
  through `cart_id` (one order per cart: unique on `order_id`, `sales_order`
  and `cart_id`).

## Recorded Decisions

1. **Region/sales-channel resolution** — provider-configured Region and Sales
   Channel resolve the ERPNext `Company`, `Price List`, `Warehouse`,
   `Territory` and `Cost Center` from Ceto configuration tables; they are
   never inferred from customer data.
2. **Guest carts** — carts without an authenticated customer use a single
   configured Guest Customer as `party_name`.
3. **Authenticated customer identity** — Frappe `User` → `Contact` →
   `Customer`: the Medusa `customer_id` maps to a Customer whose Contact is
   linked to the Frappe User created at signup. A user linked to multiple
   distinct Customers is ambiguous and rejected as unauthorized rather than
   resolved arbitrarily.
4. **Cart addresses** — addresses captured at checkout are cart-scoped
   temporary `Address` records linked to the Quotation only; on customer
   claim (transfer) or cart completion a customer-linked copy is created and
   the Quotation is relinked to that copy.
5. **Publishable key** — validated at the HTTP boundary (middleware) only;
   it selects the sales channel/region configuration and is not persisted on
   cart records.
6. **Store credits** — applied cart credits are held as `Ceto Cart Credit
   Reservation` rows in the Ceto provider ledger and surfaced on the
   Quotation as negative `Actual` tax rows (Phase 5); the wallet balance is
   debited in the provider ledger only at completion time, inside the same
   locked transaction that places the order (Phase 6).
   Credits never create ERPNext payment vouchers.
7. **Payment readiness gate** — before creating the Sales Order, cart
   completion consults the registered `ceto_cart_payment_readiness` provider
   hooks. With no provider registered the gate is open and completion
   proceeds; the first falsy hook verdict refuses the completion closed
   before any money moves or any order is created.
8. **No Custom Fields** — every Medusa field without an ERPNext equivalent is
   classified **gap** and handled by Ceto compatibility doctypes/behavior
   only; no Custom Fields are added to core ERPNext doctypes.
9. **Order display ids** — Ceto orders carry only the public `order_…` id.
   Medusa's `display_id` / `custom_display_id` are omitted: no ERPNext
   equivalent exists and the ERPNext Sales Order name stays internal to the
   `Ceto Order Reference` mapping.

## Demonstrated Phase 0 behavior

`ceto.tests.services.carts.test_conversion` proves on an ERPNext test site that
an Item Price supplies a Shopping Cart Quotation line rate; ERPNext calculates
a document-level discount, percentage tax, explicit shipping charge, and grand
total; and the standard Quotation mapper preserves those values and the source
Quotation Item link in a submitted Sales Order.

The proof materializes the coupon result as an additional discount and shipping
as an `Actual` taxes-and-charges row. A Coupon Code or Shipping Rule master link
is not guaranteed to be copied to the Sales Order, so later adapters must treat
the calculated transaction rows and totals—not those master links—as the
completion boundary.
