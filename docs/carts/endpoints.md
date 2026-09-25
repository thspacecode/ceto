# Store Cart Endpoints — Source of Truth (Phase 0)

Phase 0 of the carts work does **not** implement cart API handlers. It pins a
machine-readable contract manifest that later phases implement against.

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
