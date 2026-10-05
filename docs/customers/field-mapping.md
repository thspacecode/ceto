# Store Customers — Medusa → ERPNext Field Mapping (Phase 0)

Classification legend for every mapping row (same convention as
`docs/carts/field-mapping.md`):

- **direct** — the Medusa field maps 1:1 onto an ERPNext field (possibly with
  type coercion).
- **derived** — the ERPNext field is computed from one or more Medusa fields
  or Ceto configuration.
- **gap** — no ERPNext equivalent exists; handled by a Ceto compatibility
  layer (Ceto doctypes / behavior), **not** by Custom Fields on core ERPNext
  doctypes. Phase 0 records the gap only.

Sources: pinned `@medusajs/types@2.21.1` (`http/customer/store`) and
`@medusajs/js-sdk@2.21.1` (see `docs/customers/endpoints.md`).

## Customer → Contact + Customer (+ User)

One Medusa `StoreCustomer` spans three ERPNext/Frappe records: the Frappe
`User` is the login identity, the `Contact` carries the profile columns, and
the `Customer` is the selling party carts and orders already reference.

| Medusa `StoreCustomer` field | ERPNext / Frappe target | Classification |
|---|---|---|
| `id` (`cus_…`) | Ceto external-identity record linked to `Customer.name` | gap |
| `email` | Frappe `User` name (the registration identity) and `Contact.email_id` | direct |
| `first_name`, `last_name` | `Contact.first_name` / `Contact.last_name`; composed into `Customer.customer_name` | direct/derived |
| `company_name` | `Contact.company_name` | direct |
| `phone` | `Contact.phone` | direct |
| `default_billing_address_id` | `is_primary_address` of the linked `Address` rows (the flagged one) | derived |
| `default_shipping_address_id` | `is_shipping_address` of the linked `Address` rows (the flagged one) | derived |
| `addresses` | `Address` docs linked to the `Customer` through Dynamic Links | derived |
| `metadata` | Ceto compatibility layer | gap |
| `created_at` / `updated_at` | `Customer.creation` / `Customer.modified` | direct |
| `created_by` | omitted — the pinned `StoreCustomer` is `Omit<BaseCustomer, "created_by">` and publishes no creator | gap |
| `deleted_at` | omitted — Ceto policy: no soft-deleted customer surface exists in Phase 0 | gap |

## StoreCustomerAddress → Address

| Medusa `StoreCustomerAddress` field | ERPNext `Address` field | Classification |
|---|---|---|
| `id` | `name` (the public id **is** the Address name; API-created entries use Ceto's own naming, mirroring the cart temp addresses `CAR-Addr-…`) | derived |
| `customer_id` | Dynamic Link `Address` ↔ `Customer` (serialized as the public `cus_…` id) | derived |
| `address_name` | `address_title` (label precedence over the composed names) | direct |
| `first_name`, `last_name` | composed into `address_title` when `address_name` is absent — no dedicated ERPNext columns | derived |
| `company` | `address_title` suffix / Ceto mapping (cart-address precedent) | direct |
| `address_1`, `address_2` | `address_line1`, `address_line2` | direct |
| `city`, `province`, `postal_code` | `city`, `state`, `pincode` | direct |
| `country_code` | `country` (resolve ISO code to the ERPNext Country name) | derived |
| `phone` | `phone` | direct |
| `is_default_billing` | `is_primary_address` | direct |
| `is_default_shipping` | `is_shipping_address` | direct |
| `metadata` | Ceto compatibility layer | gap |
| `created_at` / `updated_at` | `creation` / `modified` | direct |

Address-book entries are customer-linked `Address` records (Dynamic Link),
unlike the cart-scoped temporary Addresses of the cart flow; a cart claim
already copies captured temporaries into exactly this shape.

## Query envelope decisions (recorded in the contract, not decisions below)

- `fields` — the pinned `SelectParams` selector applies to routes 1–7; Ceto
  always serializes the `addresses` relation on the customer (Ceto policy:
  the address book loads with the customer and checkout needs it); the delete
  route has a fixed shape and its pinned manifest carries no query contract,
  so every parameter — `fields` included — is rejected there.
- Pagination — Ceto policy window: `offset` defaults to 0, `limit` defaults
  to 20 with a maximum of 100; the response always reports the applied
  `count` / `offset` / `limit`. The pinned `PaginatedResponse.estimate_count`
  is never reported: the Postgres planner estimate has no ERPNext equivalent.
- `with_deleted` — accepted and validated per the pinned `FindParams`; Ceto
  keeps no soft-deleted address surface, so it is a validated no-op.
- Filters — the pinned `StoreCustomerAddressFilters` drops `company` and
  `province` (pinned `Omit`), so Ceto rejects them; `country_code` is
  normalized to a two-letter lowercase code like every address payload.
  Filters accept the single-value member of the pinned `string | string[]`
  unions only (single-member policy, same as the cart shipping-methods body).

## Recorded Decisions

1. **Public customer ids** — the public customer id is `cus_` + 128 bits of
   cryptographic random (`secrets.token_hex(16)`), the same shape as the
   `cart_…` / `order_…` / `li_…` / `cl_…` ids. It names a Ceto
   external-identity record linked to the ERPNext `Customer` (gap, backed by
   the Ceto-owned `Ceto Customer Reference` DocType delivered in Phase 1:
   one-to-one by unique schema on the public id, the `Customer` and the
   owning `User`, with the metadata columns the contract needs). ERPNext
   Customer names never appear in the customer contract.
2. **Contact/Customer model and naming** — one Medusa customer is one Frappe
   `User` (Website User named by the registered email) → `Contact` (via
   `Contact.user`) → `Customer` (Dynamic Link), the exact identity chain the
   cart claim resolves; one Customer per user, an ambiguous multi-Customer
   link is rejected as unauthorized, never resolved arbitrarily. Customers
   created through the API are `customer_type: "Individual"` with
   `customer_name` composed from the profile names and the email as fallback
   (Ceto policy); the `Contact` carries the profile columns.
3. **Email immutability** — the pinned `StoreUpdateCustomer` is
   `Omit<BaseUpdateCustomer, "email">`, so the update payload has no `email`
   field and an `email` key in the body is rejected as an unknown field
   (`400 invalid_data`). The email is the login identity (it names the Frappe
   `User`); changing it requires the auth verification flow, which stays out
   of the customers API. On create, the identity is the registration token's
   subject: a body email that disagrees is rejected and an omitted email
   falls back to the token subject (Ceto policy, mirroring the emailpass
   credential update's token/email match).
4. **Metadata** — the pinned optional `metadata` objects on the customer and
   on every address have no ERPNext equivalent; they are stored in the Ceto
   compatibility layer (gap, no Custom Fields). Merge semantics follow the
   cart metadata contract: values merge per key, a `null` value removes a
   key, an explicit `metadata: null` clears all keys.
5. **Address ids** — the public address id **is** the ERPNext `Address`
   `name`; the public address name is that ERPNext address name, exactly like
   the cart-address contract. Address-book entries
   created through the API use Ceto's own naming so public ids never leak
   ERPNext's configurable naming, while pre-existing customer Addresses are
   exposed under their existing names. `customer_id` on an address always
   serializes the owning customer's public `cus_…` id.
6. **Default billing/shipping** — `is_default_billing` ↔
   `Address.is_primary_address` and `is_default_shipping` ↔
   `Address.is_shipping_address` (direct). Per customer there is at most one
   default of each kind: setting a flag clears the previous holder and
   `default_billing_address_id` / `default_shipping_address_id` are derived
   from the flagged rows. The per-customer exclusivity is Ceto policy — the
   ERPNext checkboxes are not customer-scoped.
7. **Publishable-key policy** — every customer route requires the
   `x-publishable-api-key` header, validated at the HTTP boundary only and
   never persisted (extends carts decision 5). Customers carry no
   region/sales-channel scope, so there is no per-record scope guard like the
   cart mutation guard (Ceto policy).
8. **Registration-token replay** — `POST /store/customers` consumes the
   single-purpose `registration` bearer token exactly once: the first
   successful create binds the token subject to its new User/Contact/Customer.
   Any replay of a consumed token — including one for an identity that
   already owns a Customer — is rejected as `401 unauthorized`, so the route
   can never mint a second customer for one identity and cannot be used to
   enumerate registrations (Ceto policy on top of the purpose-bound token
   contract; Medusa delegates the equivalent check to its identity service).
9. **Address deletion semantics** — the pinned delete contract responds
   `{id, object: "address", deleted: true, parent: StoreCustomer}`; Ceto
   mirrors the soft-delete semantics by unlinking the Customer ↔ Address
   Dynamic Link (the address leaves the address book and `404`s afterwards —
   the unlink is authoritative, removed directly so the entry leaves the book
   even when the Address controller's owner-based relink would re-attach the
   Customer link for an entry the customer's own user owns),
   clearing the customer's default slot when the deleted address held one,
   and destroying the ERPNext `Address` document only when nothing references
   it — placed orders and quotations keep their historical address (Ceto
   policy).

## Demonstrated Phase 0 behavior

None by design: Phase 0 is contract-only. The proof surface is the pure type
suite (`ceto.tests.types.http.store.test_customers_*`) and the manifest/docs
drift tests (`ceto.tests.types.http.store.test_customers_manifest`,
`ceto.tests.docs.test_customers_endpoints`,
`ceto.tests.docs.test_customers_field_mapping`); no endpoint behavior, service
or DocType is added, and no README route is marked implemented.
