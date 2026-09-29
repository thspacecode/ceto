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
| `subtotal`, `item_subtotal` | `net_total` / item totals (recomputed by ERPNext) | derived |
| `discount_total`, `discount_subtotal` | `additional_discount_percentage` / pricing-rule discounts | derived |
| `shipping_total` | Shipping Rule charge row | derived |
| `tax_total` | tax rows on Quotation Item / taxes and charges | derived |
| `total` | `grand_total` (must reconcile after recalculation) | derived |
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
relinked to that copy.

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
| `shipping_option_id` | `shipping_rule` on the Quotation | derived |
| `name` | Shipping Rule title | direct |
| `amount` | Shipping Rule rate | direct |
| `subtotal`, `total`, `tax_total` | shipping tax rows in taxes and charges | derived |

## Tax Lines → Quotation taxes and charges

| Medusa tax line field | ERPNext target | Classification |
|---|---|---|
| `item_tax_line.rate_id` / description | Sales Taxes and Charges Template row | derived |
| `rate` | row `rate` (%) or `tax_amount` (absolute) | direct |
| `code`, `name` (provider tax code) | `account_head` resolution via Ceto tax-code map | derived |
| `shipping_tax_line` | shipping tax row | derived |
| Medusa per-item inclusive/exclusive modes (`item_tax_mode`) | `included_in_print_rate` handling | gap |

## Completion → Sales Order

| Medusa `StoreCompleteCartResponse` (`order`/`cart` union) | ERPNext target | Classification |
|---|---|---|
| `order` on success | Quotation → Sales Order (submit Quotation output, then submit Sales Order) | derived |
| `type: "cart"` (incomplete) | Quotation left open; completion error surfaced | gap |
| `payment_collection` requirement | Ceto requires payment readiness (authorized/captured per provider settings) **before** creating the Sales Order | gap |
| `order.id`, `order.display_id` | Ceto order-correlation record (Sales Order ↔ Medusa order id) | gap |
| payment status / credits | tracked in the provider ledger; credits recorded later | gap |

## Recorded Decisions

1. **Region/sales-channel resolution** — provider-configured Region and Sales
   Channel resolve the ERPNext `Company`, `Price List`, `Warehouse`,
   `Territory` and `Cost Center` from Ceto configuration tables; they are
   never inferred from customer data.
2. **Guest carts** — carts without an authenticated customer use a single
   configured Guest Customer as `party_name`.
3. **Authenticated customer identity** — Frappe `User` → `Contact` →
   `Customer`: the Medusa `customer_id` maps to a Customer whose Contact is
   linked to the Frappe User created at signup.
4. **Cart addresses** — addresses captured at checkout are cart-scoped
   temporary `Address` records linked to the Quotation only; on customer
   claim (transfer) or cart completion a customer-linked copy is created and
   the Quotation is relinked to that copy.
5. **Publishable key** — validated at the HTTP boundary (middleware) only;
   it selects the sales channel/region configuration and is not persisted on
   cart records.
6. **Store credits** — store-credit amounts are recorded in the Ceto provider
   ledger at completion time (later phase); they do not create ERPNext
   vouchers during Phase 0.
7. **Payment readiness gate** — cart completion refuses to create the Sales
   Order until payment readiness is confirmed by the payment provider
   integration (per provider settings).
8. **No Custom Fields** — every Medusa field without an ERPNext equivalent is
   classified **gap** and handled by Ceto compatibility doctypes/behavior
   only; no Custom Fields are added to core ERPNext doctypes.

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
