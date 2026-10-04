# Store Customer Endpoints — Source of Truth

Phase 0 pins a machine-readable contract manifest that later phases implement
against. **No customer route is registered yet**: this phase deliberately adds
no handler, no service and no DocType, and the README keeps every customer
route at ⚪️ until an implementation phase lands. The coverage guard for this
phase is the manifest drift test (`ceto.tests.types.http.store.test_customers_manifest`)
plus the docs↔manifest inventory check (`ceto.tests.docs.test_customers_endpoints`);
once the routes are registered, `ceto.tests.routing.test_router` must compare
the registered surface with `CUSTOMER_ROUTES`, exactly as it does for carts.

## Manifest

- Module: `ceto/types/http/store/customers/manifest.py`
- Tests: `ceto/tests/types/http/store/test_customers_manifest.py`
- API source (pinned): <https://docs.medusajs.com/api/store/customers>
- JS SDK (pinned): `@medusajs/js-sdk@2.21.1`
- HttpTypes (pinned): `@medusajs/types@2.21.1` (`http/customer/store` for the
  domain contracts, `http/common` for the shared `SelectParams` selector)

Both pins are the same lockstep release the carts contract uses. They were
verified against the published packages themselves (`sdk.store.customer`
fetch paths and the `HttpTypes` interfaces), not against documentation alone.
The legacy storefront under the migration source
(`/home/node/ref/mono/apps/storefront`) carries no Medusa SDK dependency, so
the published packages are the only customer-contract source.

The manifest is pure Python (`dataclass` entries, no Frappe imports) so it can
be consumed by request validation codegen and tested standalone.

## Pinned routes (8)

| # | Method | Path | Request type | Response type | Query type | Auth | SDK method |
|---|--------|------|--------------|---------------|------------|------|------------|
| 1 | POST | `/store/customers` | `StoreCreateCustomer` | `StoreCustomerResponse` | `SelectParams` | pk + registration token | `create` |
| 2 | GET | `/store/customers/me` | — | `StoreCustomerResponse` | `StoreGetCustomerParams` | pk + customer session | `retrieve` |
| 3 | POST | `/store/customers/me` | `StoreUpdateCustomer` | `StoreCustomerResponse` | `SelectParams` | pk + customer session | `update` |
| 4 | GET | `/store/customers/me/addresses` | — | `StoreCustomerAddressListResponse` | `StoreCustomerAddressFilters` | pk + customer session | `listAddress` |
| 5 | POST | `/store/customers/me/addresses` | `StoreCreateCustomerAddress` | `StoreCustomerResponse` | `SelectParams` | pk + customer session | `createAddress` |
| 6 | GET | `/store/customers/me/addresses/{address_id}` | — | `StoreCustomerAddressResponse` | `StoreGetCustomerAddressParams` | pk + customer session | `retrieveAddress` |
| 7 | POST | `/store/customers/me/addresses/{address_id}` | `StoreUpdateCustomerAddress` | `StoreCustomerResponse` | `SelectParams` | pk + customer session | `updateAddress` |
| 8 | DELETE | `/store/customers/me/addresses/{address_id}` | — | `StoreCustomerAddressDeleteResponse` | — | pk + customer session | `deleteAddress` |

## Source of truth vs. SDK compatibility

The **API reference URL** is the source of truth for route shape, request and
response types. The **JS SDK** is a compatibility layer only:

- `@medusajs/js-sdk@2.21.1` directly supports all 8 customer routes through
  `create`, `retrieve`, `update`, `listAddress`, `createAddress`,
  `retrieveAddress`, `updateAddress` and `deleteAddress`. Unlike the carts
  surface, no customer route needs a raw HTTP client.
- The SDK sends `query` only on routes 1–7; the delete route carries no query
  parameters (fixed response shape).

When Medusa ships a new version, update `CUSTOMER_API_SOURCE_URL`,
`CUSTOMER_SDK_VERSION` and the manifest entries together, then fix the tests —
they intentionally fail on drift.

## Authentication

Every customer route requires the `x-publishable-api-key` header, like every
Medusa Store route (publishable-key policy: boundary validation only, see the
recorded decisions in `field-mapping.md`).

- **Route 1** (`POST /store/customers`) authenticates with the single-purpose
  `registration` bearer token issued by `POST /auth/customer/{auth_provider}`
  (register). Ceto's register route creates neither User nor Customer, so the
  create call is the first step that mints the customer identity. The token is
  purpose-bound (`purpose: registration`): an `auth`-purpose token never
  authenticates it, and the replay policy is a recorded decision (below).
- **Routes 2–8** authenticate the customer (Frappe session cookie or
  `auth`-purpose bearer token). A guest request fails with `401 unauthorized`,
  as does a session user with no Customer linked through its `Contact` (the
  same resolver the cart claim uses).

## Query behavior

- **`fields`** (routes 1–7): the pinned `SelectParams` selector. Ceto always
  serializes the `addresses` relation on the customer by default (Ceto policy:
  the address book loads with the customer and checkout needs it); `fields`
  projects on top of that baseline. The delete route (8) has a fixed shape and
  ignores `fields`.
- **Pagination** (route 4 only): `limit`, `offset`, `order`, `with_deleted`
  per the pinned `FindParams`. Window bounds are Ceto policy: `offset`
  defaults to 0, `limit` defaults to 20 with a maximum of 100. The response
  always reports the applied window as required `count` / `offset` / `limit`;
  the Postgres planner `estimate_count` of the pinned `PaginatedResponse` is
  never reported (no ERPNext equivalent).
- **Filters** (route 4 only): `q`, `city`, `country_code`, `postal_code` —
  the pinned `StoreCustomerAddressFilters` deliberately drops `company` and
  `province` from the base filters, so Ceto rejects them too. Filters accept
  the single-value member of the pinned `string | string[]` unions only.
- **Unknown parameters** are rejected (`400 invalid_data`) on every route,
  like every Ceto contract.

## Contract decisions

All Phase 0 decisions — public customer ids, the Contact/Customer model,
email immutability, metadata, address ids, the default billing/shipping
flags, publishable-key handling, registration-token replay and address
deletion semantics — are recorded with their sources in
[docs/customers/field-mapping.md](./field-mapping.md).

## Implemented routes

None. Phase 0 is contract-only.
