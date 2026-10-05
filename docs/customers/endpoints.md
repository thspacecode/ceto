# Store Customer Endpoints — Source of Truth

Phase 0 pinned the machine-readable contract manifest that implementation
phases build against. **Phase 3 registers the complete surface** — all eight
pinned routes, from `POST /store/customers` through the five address-book
routes under `/store/customers/me/addresses` (see
[Implemented routes](#implemented-routes)); the README marks every customer
route ✅. The coverage guard is the
manifest drift test
(`ceto.tests.types.http.store.test_customers_manifest`), the docs↔manifest
inventory check (`ceto.tests.docs.test_customers_endpoints`) and the router
surface check in `ceto.tests.routing.test_router`, which compares the
registered customer routes with the implemented manifest subset, exactly as it
does for the completed carts surface.

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
  `registration` bearer token issued by
  `POST /auth/customer/{auth_provider}/register`. That register route creates
  only the login Website User — never the ERP Customer profile — so the
  create call is the step that completes the registration by minting the
  profile. The token is purpose-bound (`purpose: registration`): an
  `auth`-purpose token never authenticates it, and the replay policy is a
  recorded decision (below).
- **Routes 2–8** authenticate the customer (Frappe session cookie or
  `auth`-purpose bearer token). A guest request fails with `401 unauthorized`,
  as does a session user with no Customer linked through its `Contact` (the
  same resolver the cart claim uses).

## Query behavior

- **`fields`** (routes 1–7): the pinned `SelectParams` selector. Ceto always
  serializes the `addresses` relation on the customer by default (Ceto policy:
  the address book loads with the customer and checkout needs it); `fields`
  projects on top of that baseline — `+`/`-`/`*` tokens add, remove or reset
  on it, and on the address projections (routes 4 and 6) the collapsed label
  trio (`first_name`, `last_name`, `company` — no dedicated columns, they
  never serialize back) and any unknown field are refused
  (`400 invalid_data`). The delete route (8) has a fixed shape and ignores
  `fields`.
- **Pagination** (route 4 only): `limit`, `offset`, `order`, `with_deleted`
  per the pinned `FindParams`. Window bounds are Ceto policy: `offset`
  defaults to 0, `limit` defaults to 20 with a maximum of 100. The response
  always reports the applied window as required `count` / `offset` / `limit`;
  the Postgres planner `estimate_count` of the pinned `PaginatedResponse` is
  never reported (no ERPNext equivalent). `with_deleted` validates and is a
  no-op — Ceto keeps no soft-deleted address surface.
- **Ordering** (route 4 only): deterministic — the default is
  `creation asc, name asc`; an explicit `order` may name `id`, `created_at`,
  `updated_at`, `address_name`, `city` or `postal_code` with an optional
  `+`/`-` direction and always carries the `name` tiebreak so equal sort keys
  keep a stable order. An unknown or empty order field is `400 invalid_data`.
- **Filters** (route 4 only): `q`, `city`, `country_code`, `postal_code` —
  the pinned `StoreCustomerAddressFilters` deliberately drops `company` and
  `province` from the base filters, so Ceto rejects them too. Filters accept
  the single-value member of the pinned `string | string[]` unions only.
  `q` sweeps the label and street/city columns as a case-insensitive
  substring (`address_title`, `address_line1`, `address_line2`, `city`);
  `city` and `postal_code` match exactly; `country_code` must be a two-letter
  ISO 3166-1 alpha-2 code that resolves to an ERPNext `Country`.
- **Unknown parameters** are rejected (`400 invalid_data`) on every route,
  like every Ceto contract.

## Contract decisions

All Phase 0 decisions — public customer ids, the Contact/Customer model,
email immutability, metadata, address ids, the default billing/shipping
flags, publishable-key handling, registration-token replay and address
deletion semantics — are recorded with their sources in
[docs/customers/field-mapping.md](./field-mapping.md).

## Implemented routes

Phase 3 completes the pinned surface: Phase 2 implemented routes 1–3 and
Phase 3 adds the address book (routes 4–8) — all eight README rows are ✅.

### `POST /store/customers` — `ceto.api.store.customers.create_customer`

- Guest-dispatchable Store route that authenticates with the single-purpose
  `registration` bearer token issued by
  `POST /auth/customer/{auth_provider}/register`; an `auth`-purpose token never
  works. The token's own `provider` claim must name an enabled customer auth
  provider.
- The identity is the token subject (recorded decision 3): an omitted body
  email falls back to it and a disagreeing one is refused with
  `400 invalid_data`, mirroring the credential update's token/email match.
- The profile is created inside the request transaction
  (`ceto.services.customers.creation.create_customer_profile`); a disabled,
  pre-owned or ambiguous identity is refused with `401 unauthorized` before
  any privileged write.
- The token is consumed only after the profile transaction **and** the
  response serialization succeeded (recorded decision 8): the used-marker
  lives in cache and survives the router's rollback, so a failed create never
  burns the token — the identical request can be retried. A replay of a
  consumed token is always `401 unauthorized` and never binds a second
  profile.
- The pinned `SelectParams` `fields` selector projects the serialized
  customer; unknown selectors are rejected (`400 invalid_data`).

### `GET /store/customers/me` — `ceto.api.store.customers.retrieve_customer`

- Requires the publishable key plus an authenticated customer: a Frappe
  session or an `auth`-purpose bearer token (resolved by the shared auth
  hook). The router refuses guests before the handler runs; registration and
  password-reset tokens never authenticate.
- The session user resolves through the shared identity resolver
  (`ceto.services.customers.identity.resolve_customer_reference`): no Contact
  chain, no Customer, or no Ceto Customer Reference is masked as the same
  `401 unauthorized` — a response never confirms which identities exist.
- Same pinned `StoreCustomerResponse` shape and `fields` selector as the
  create route; the `addresses` relation always serializes (empty until the
  address-book phase).

### `POST /store/customers/me` — `ceto.api.store.customers.update_customer`

- Same authenticated gate as the retrieve route: the publishable key is
  validated first and the router refuses guests before the handler runs; a
  Frappe session or an `auth`-purpose bearer token authenticates through the
  shared auth hook, while registration and password-reset tokens never do.
- The identity chain and its `Ceto Customer Reference` resolve through the
  shared resolver **before** any privileged write: no Contact chain, no
  Customer or no reference is masked as the same `401 unauthorized` and
  writes nothing. The update only ever reaches the authenticated customer's
  own chain — a resolved peer profile is never touched.
- The body validates against the pinned `StoreUpdateCustomer` before the
  resolver runs. `email` is not part of the update contract (recorded
  decision 3 — the login identity changes through the auth verification
  flow), so an `email` key is refused like every unknown field with
  `400 invalid_data`, alone or beside an otherwise valid update, and no
  mutation happens.
- The update is partial (`payload.model_fields_set`): an omitted field
  leaves its stored value untouched; a present `null` — or a stripped empty
  string, which the pinned payload model already normalized to `""` —
  clears it. `first_name` / `last_name` / `company_name` are Contact
  profile columns; an empty payload writes nothing at all.
- `phone` moves the Contact's primary `phone_nos` child row (recorded
  decision 2): the derived `Contact.phone` column is never written directly
  — the Contact controller recomputes it from the primary flag on every
  save. A clear releases the primary slot (any other row, e.g. a
  CRM-managed number, survives); a new value promotes the row that already
  carries the number or appends it as the only primary.
- `metadata` merges with the shared reference semantics (recorded
  decision 4): values merge per key, a `null` value removes a key and an
  explicit `metadata: null` clears all keys; a no-op metadata change writes
  nothing.
- Every effective profile or metadata mutation also saves the `Customer`,
  so `customer_name` recomposes from the effective names with the identity
  email as fallback (recorded decision 2) and the contract's `updated_at`
  advances. The saves stay unlocked inside the request transaction, so a
  lost race surfaces as the standard optimistic-concurrency error.
- The pinned `SelectParams` `fields` selector projects the freshly
  serialized customer *after* the update ran: an invalid selector fails
  with `400 invalid_data` and the router rolls the whole request back —
  applied writes included.
- Same pinned `StoreCustomerResponse` shape and serializer as routes 1–2;
  the `addresses` relation always serializes.

### `GET /store/customers/me/addresses` — `ceto.api.store.customers.list_customer_addresses`

- Same authenticated gate as the profile routes: the publishable key is
  validated first and the router refuses guests before the handler runs; a
  Frappe session or an `auth`-purpose bearer token authenticates through the
  shared auth hook, while registration and password-reset tokens never do.
- The strict pinned query (`StoreCustomerAddressFilters`) validates before
  the identity resolves: unknown parameters are `400 invalid_data`, including
  the `company` and `province` filters the pinned type deliberately drops,
  and only the single-value member of the pinned `string | string[]` unions
  is accepted.
- The window is Ceto policy (`offset` 0, `limit` 20 with a maximum of 100,
  `limit=0` refused); the body always reports the applied `count` / `offset`
  / `limit` and never an `estimate_count`. `with_deleted` validates and is a
  no-op — Ceto keeps no soft-deleted address surface.
- The customer's enabled entries — including pre-existing customer Addresses
  under their existing names (recorded decision 5) — resolve as one bounded
  per-user list, ordered deterministically (see *Ordering* above), the window
  slices it and every page row projects through the pinned `fields`
  selector.

### `POST /store/customers/me/addresses` — `ceto.api.store.customers.create_customer_address`

- Same authenticated gate. The body validates against the pinned
  `StoreCreateCustomerAddress` before the identity resolves: an unknown field
  is `400 invalid_data` and nothing is written; `address_1`, `city` and
  `country_code` are required, and `country_code` must be a two-letter ISO
  code that resolves to an ERPNext `Country`.
- The identity chain resolves first (the same `401 unauthorized` mask as the
  profile routes) and the entry is created inside the request transaction:
  the public id is Ceto's stable `addr_` + 128 bits name minted onto the
  ERPNext `Address` itself, with exactly one Dynamic Link — the owning
  `Customer`, never a Quotation or Contact (recorded decision 5).
- The label trio collapses into `address_title` as `address_name`, then
  first+last name, then company; the collapsed fields never serialize back
  and the pinned selector refuses them like unknown fields.
- `metadata` lives on the entry's `Ceto Customer Address Reference` record
  (recorded decision 4) and a supplied default flag clears the previous
  per-customer holder through the normal Address controller (recorded
  decision 6), so the parent's derived `default_billing_address_id` /
  `default_shipping_address_id` already reflect the new entry.
- The response is the pinned parent customer serialized fresh (address book
  included) *after* the create; the `fields` selector projects it afterwards
  — an invalid selector fails with `400 invalid_data` and the router rolls
  the created entry back with the whole request.

### `GET /store/customers/me/addresses/{address_id}` — `ceto.api.store.customers.retrieve_customer_address`

- Same authenticated gate; the strict pinned query
  (`StoreGetCustomerAddressParams`) carries only the `fields` selector.
- Ownership masking: a missing, foreign (no `Customer` Dynamic Link to the
  caller) or disabled entry renders the same `404 not_found` — a response
  never confirms which addresses exist.
- The entry serializes to the pinned `StoreCustomerAddress`: the stable
  public id is the ERPNext `Address` name (recorded decision 5), `customer_id`
  is the owning customer's public `cus_…` id, `metadata` is the decoded
  reference record and `created_at` / `updated_at` come from `creation` /
  `modified`. The `fields` selector projects the entry; the collapsed label
  trio and unknown fields are refused like every Ceto contract.

### `POST /store/customers/me/addresses/{address_id}` — `ceto.api.store.customers.update_customer_address`

- Same authenticated gate. The pinned partial payload validates before the
  identity resolves — an unknown field is `400 invalid_data` and a missing or
  foreign entry is the same masked `404 not_found` — before anything is
  written.
- Only the fields present on the validated payload move
  (`payload.model_fields_set`): an omitted field leaves its column
  untouched; a present `null` — or a stripped empty string, which the pinned
  payload model already normalized to `""` — clears it. Clearing a pinned
  core column (`address_1`, `city`, `country_code`) is refused with
  `400 invalid_data`.
- The label recomposes only when the payload supplies a label field:
  `address_name` wins over the supplied names over the supplied company
  (recorded decision 5 mapping).
- The default flags move the ERPNext checkboxes and the controller clears the
  previous per-customer holder (recorded decision 6); `metadata` merges
  through the reference with the shared semantics (recorded decision 4). A
  no-op payload writes nothing; every effective change saves the entry, so
  its `modified` — the contract's `updated_at` — advances.
- The response is the pinned parent customer serialized after the update and
  the `fields` selector projects it afterwards: an invalid selector fails
  with `400 invalid_data` and the router rolls the applied update back with
  the whole request.

### `DELETE /store/customers/me/addresses/{address_id}` — `ceto.api.store.customers.delete_customer_address`

- Same authenticated gate; the delete contract has no query parameters and a
  fixed response shape, so no `fields` selector applies.
- Ownership masking: a missing or foreign entry renders the same
  `404 not_found` and a foreign entry is never touched.
- Integrity (recorded decision 9): the customer's ERPNext default-address
  slot is released when it names the entry; a sole-owned entry is then
  destroyed through the normal ERPNext delete — static links from placed
  orders and quotations raise `LinkExistsError` and the entry is retained
  instead, the link check is never bypassed — while an entry another Customer
  still owns is retained untouched for that owner and only unlinked from this
  book. The `Ceto Customer Address Reference` is dropped either way, so the
  entry `404`s here afterwards.
- The response is the fixed `{id, object: "address", deleted: true, parent}`
  shape: the removed id plus the unchanged parent customer, serialized after
  the deletion (empty `addresses`, cleared derived default ids).

Every refusal above renders the Medusa error envelope
(`{"type": "unauthorized" | "invalid_data" | "not_found", "message": …}`):
authentication failures — missing or unconfigured key, guest, wrong-purpose
token, replayed registration token — collapse to the stable
`401 unauthorized`, and the address ownership mask is always the same
`404 not_found`.
