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
