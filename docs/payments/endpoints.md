# Store Payment Endpoints — Source of Truth

Phase 5 slices 5A/5B pinned the machine-readable contract manifest and built
the Ceto-side persistence; **slices 5C/5D register the complete pinned
surface** — all three routes from `GET /store/payment-providers` through the
two collection routes (see [Implemented routes](#implemented-routes)) — and
the README marks every payment route ✅. The manifest is pure Python
(`ceto/types/http/store/payments/manifest.py`, contract-only); the coverage
guards are the manifest drift tests
(`ceto.tests.types.http.store.test_payments_manifest`), the docs↔manifest
inventory check (`ceto.tests.docs.test_payments_endpoints`) and the router
surface check in `ceto.tests.routing.test_router`, which compares the
registered payment routes with the implemented manifest subset, exactly as
it does for the completed carts, customers and orders surfaces.

## Manifest

- Module: `ceto/types/http/store/payments/manifest.py`
- Tests: `ceto/tests/types/http/store/test_payments_manifest.py`
- API source (pinned): <https://docs.medusajs.com/api/store/payment-collections>
  and <https://docs.medusajs.com/api/store/payment-providers>
- JS SDK (pinned): `@medusajs/js-sdk@2.21.1`
- HttpTypes (pinned): `@medusajs/types@2.21.1` (`http/payment/store` for the
  domain contracts)
- Server (verified): `@medusajs/medusa@2.21.1` — the route set, the per-route
  middlewares and the strict validators are facts the SDK/types packages do
  not carry

All pins are the same lockstep release the carts contract uses. The legacy
storefront under the migration source
(`/home/node/ref/mono/apps/storefront`) carries no Medusa SDK dependency, so
the published packages are the only payment-contract source.

## Pinned routes (3)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | POST | `/store/payment-collections` | `StoreCreatePaymentCollection` | `StorePaymentCollectionResponse` | `SelectParams` (`fields`) | publishable-key+optional-session | — (inlined in `initiatePaymentSession`) |
| 2 | POST | `/store/payment-collections/{id}/payment-sessions` | `StoreInitializePaymentSession` | `StorePaymentCollectionResponse` | `SelectParams` (`fields`) | publishable-key+optional-session | `initiatePaymentSession` |
| 3 | GET | `/store/payment-providers` | — | `StorePaymentProviderListResponse` | `StoreGetPaymentProvidersParams` | publishable-key | `listPaymentProviders` |

The pinned server release serves **no** store session update/delete/authorize
routes: checkout creates the cart's collection and one session on it, then
completes the cart. Session state changes arrive server-side — paygi's
verified webhook synchronizes captures (see
[field-mapping.md](./field-mapping.md)).

## Implemented routes

### `POST /store/payment-collections`

Returns the cart's payment collection, creating it when missing (one
collection per cart lifetime — an existing one is returned as-is). The
strict body carries exactly `cart_id`; amount and currency are derived
server-side from the cart's current payable. The publishable-key scope is
checked inside the cart row lock before any write; an unknown or foreign
cart is a masked `404 not_found`, a zero-payable cart refuses with
`400 invalid_data` (a free cart needs no payment state).

### `POST /store/payment-collections/{id}/payment-sessions`

Books the collection's current session for `provider_id` (plus the
provider's optional `data` payload), idempotently: the same provider against
an unchanged payable returns the same `pending` session, while a changed
amount, currency or provider makes the old session stale and books a fresh
one. The charge is then created through the narrow paygi boundary —
idempotency keyed on the session id, minor units converted exactly — and
the provider's response becomes the session's `data`. Provider absence or
failure is stable: a `pending` session with empty `data`, never an
accidental `500`. The whole collection is the answer.

### `GET /store/payment-providers`

Pages the enabled payment providers with the upstream defaults
(`limit` 20, `offset` 0) under the pinned
`{payment_providers, count, offset, limit}` envelope. `region_id` is
required — the route refuses without it — and is publishable-key-scope
checked; the query is strict (unknown keys are rejected). Providers resolve
through the Ceto registry, so a site without an enabled gateway serves an
empty page, never an error.

## Authentication

The framework (`@medusajs/medusa@2.21.1`) enforces the publishable API key
for the whole `/store` namespace. None of the three payment routes adds
customer-authentication middleware — guest checkout is the pinned behavior:
`GET /store/payment-providers` is publishable-key only; the two collection
routes add an **optional** session, meaning the ownership rules decide (a
cart claimed by an authenticated customer is masked `404` for everyone else,
exactly like every cart route). Ceto mirrors both facts: the key is resolved
and required on every payment route, and cart access flows through the same
`CartAccess` lock-and-owner discipline the cart mutations use.

## Source of truth vs. SDK compatibility

The **API reference URL** is the source of truth for route shape, request
and response types. The **JS SDK** is a compatibility layer only:

- `sdk.store.payment.listPaymentProviders` maps to route 3 and
  `sdk.store.payment.initiatePaymentSession` to routes 1+2 (the SDK creates
  the cart's missing collection inline before initializing the session), so
  the full pinned surface is reachable without a raw HTTP client.
- The SDK sends `query` only on route 3; the collection routes carry `fields`
  selection and JSON bodies.

When Medusa ships a new version, update `PAYMENT_API_SOURCE_URL`,
`PAYMENT_SDK_VERSION`, `PAYMENT_TYPES_VERSION`, `PAYMENT_SERVER_VERSION` and
the manifest entries together, then fix the tests — they intentionally fail
on drift.
