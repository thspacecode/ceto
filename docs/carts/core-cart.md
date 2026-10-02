# Core cart configuration (Phase 1)

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
