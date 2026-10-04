# Store Orders — Medusa → ERPNext Field Mapping (Phase 0)

Phase 0 pins the six Store Orders route contracts
(`ceto/types/http/store/orders/manifest.py`) and records how a placed order
will be served from ERPNext. **No order route is registered or implemented
yet** — orders exist only as the completion product of the cart flow (Phase 6
`CartCompletion` + `OrderSerializer`, see `docs/carts/field-mapping.md`).
Phase 0 changes no API behavior and no schema: the `owner_customer` snapshot
on `Ceto Order Reference` and the `Ceto Order Transfer` record described
below are Phase 1 models this document pins, not artifacts it creates.

Everything in this document is labeled either an **upstream contract fact** —
verified against the pinned `@medusajs/js-sdk@2.21.1` and
`@medusajs/types@2.21.1` sources (plus the lockstep server implementation
`@medusajs/medusa@2.21.1` for the behavior those two packages do not carry:
middleware, validators, workflows) — or a **Ceto decision**, for the behavior
Medusa leaves server-defined.

Two verification results contradict the preliminary orders PRD, and both
supersessions are recorded explicitly: the transfer request is initiated by
the customer *seeking* ownership — the pinned payload carries no recipient
identifier to nominate (see *Transfer requester semantics*) — and order
retrieval is deliberately capability-based and guest-accessible (see *Order
retrieval auth*). Ceto Phase 0 chooses exact Medusa-compatible semantics in
both places.

Classification legend for every mapping row:

- **direct** — the Medusa field maps 1:1 onto an ERPNext/Ceto field (possibly
  with type coercion).
- **derived** — the ERPNext/Ceto field is computed from one or more Medusa
  fields or Ceto records.
- **gap** — no ERPNext equivalent exists; handled by a Ceto compatibility
  layer (Ceto doctypes / behavior), **not** by Custom Fields on core ERPNext
  doctypes.

## Pinned routes (Phase 0)

| # | Method | Path | Request type | Response type | Auth | SDK method |
|---|--------|------|--------------|---------------|------|------------|
| 1 | GET | `/store/orders/{id}` | — | `StoreOrderResponse` | publishable-key | `retrieve` |
| 2 | GET | `/store/orders` | — | `StoreOrderListResponse` | pk + customer session | `list` |
| 3 | POST | `/store/orders/{id}/transfer/request` | `StoreRequestOrderTransfer` | `StoreOrderResponse` | pk + customer session | `requestTransfer` |
| 4 | POST | `/store/orders/{id}/transfer/accept` | `StoreAcceptOrderTransfer` | `StoreOrderResponse` | pk + transfer token | `acceptTransfer` |
| 5 | POST | `/store/orders/{id}/transfer/cancel` | — | `StoreOrderResponse` | pk + customer session | `cancelTransfer` |
| 6 | POST | `/store/orders/{id}/transfer/decline` | `StoreDeclineOrderTransfer` | `StoreOrderResponse` | pk + transfer token | `declineTransfer` |

Verification sources (exact 2.21.1 package paths, packed and inspected outside
the repo):

- `@medusajs/js-sdk@2.21.1` — `dist/store/index.js` / `dist/store/index.d.ts`,
  the `store.order` namespace: six methods, each a single `client.fetch` with
  the paths above (`list`/`retrieve` are GETs, the four transfer calls are
  POSTs; `cancelTransfer` sends no body). `dist/client.js` sends
  `x-publishable-api-key` on every request, `Authorization: Bearer <jwt>` from
  its token store (unless session auth is configured), JSON content type, and
  serializes queries with `qs` (`skipNulls`).
- `@medusajs/types@2.21.1` — `dist/http/order/store/payloads.d.ts`
  (`StoreRequestOrderTransfer`, `StoreAcceptOrderTransfer`,
  `StoreDeclineOrderTransfer`), `dist/http/order/store/responses.d.ts`
  (`StoreOrderResponse`, `StoreOrderListResponse`),
  `dist/http/order/store/queries.d.ts` (`StoreOrderFilters`),
  `dist/http/common/request.d.ts` (`SelectParams`, `FindParams`),
  `dist/http/common/response.d.ts` (`PaginatedResponse`),
  `dist/order/common.d.ts` (`OrderStatus`).
- `@medusajs/medusa@2.21.1` (lockstep server implementation) —
  `dist/api/store/orders/middlewares.js` (per-route authentication),
  `dist/api/store/orders/validators.js` (payload shapes,
  `createFindParams({offset: 0, limit: 50})`), `dist/api/store/orders/route.js`
  and `dist/api/store/orders/[id]/route.js` (list/retrieve behavior),
  `dist/api/store/orders/[id]/transfer/*/route.js` (transfer handlers).
- `@medusajs/framework@2.21.1` — `dist/http/middlewares/ensure-publishable-api-key.js`
  and `dist/http/router.js` (publishable key enforced on the whole `/store`
  namespace).
- `@medusajs/core-flows@2.21.1` — `dist/order/workflows/transfer/` (the four
  transfer workflows), `@medusajs/utils@2.21.1` `dist/core-flows/events.js`
  (`order.transfer_requested`), `@medusajs/order@2.21.1`
  `dist/utils/actions/transfer-customer.js` (what accept applies).

The manifest pins the same contracts in machine-readable form;
`ceto.tests.types.http.store.test_orders_manifest` fails on manifest drift, on
drift against the README's Orders table, and on any premature route
registration.

## Order → ERPNext data sources

An order is a **read model** over records that already exist after completion
(no new ERPNext state): the `Ceto Order Reference` the completion booked, the
submitted ERPNext `Sales Order` it stands for, and the completed cart's
`Ceto Cart Reference` (the cart context a Sales Order never carried).
Ownership is read from the order reference itself: the Phase 1 model gives
`Ceto Order Reference` an `owner_customer` snapshot that the completing
transaction populates atomically, so effective ownership is independent of
the immutable cart history for the order's whole life.

| Medusa `StoreOrder` field | ERPNext / Ceto source | Classification |
|---|---|---|
| `id` (`order_…`) | `Ceto Order Reference.order_id` (the document name; the Sales Order name stays internal) | gap |
| `sales_order` link | `Ceto Order Reference.sales_order` (Ceto-internal, never serialized) | gap |
| `region_id`, `sales_channel_id`, `metadata` | completed cart's `Ceto Cart Reference` (via `cart_id`) | direct |
| `customer_id` | effective owner: the `Ceto Order Reference.owner_customer` snapshot (populated atomically by the completing transaction); references completed before the snapshot existed fall back to the completed cart's `Ceto Cart Reference.owner_customer` and are backfilled | derived |
| `email` | `Sales Order.contact_email` | direct |
| `currency_code` | `Sales Order.currency` (lower-cased) | direct |
| `shipping_address`, `billing_address` | `Sales Order.shipping_address_name` / `customer_address` (customer-linked Address copies made at claim/completion, carts Recorded Decision 4) | direct |
| `items[]` | `Sales Order Item` rows, identities carried over via `Ceto Cart Line Item Reference` (the client keeps the same `li_…` ids) | derived |
| `items[].unit_price`, `subtotal`, `discount_total`, `tax_total` | ERPNext row calculations copied by the mapper (`net_rate`, `net_amount`, `discount_amount`, tax allocation) | derived |
| `shipping_methods[]` | the Shipping Rule's `Actual` charge row on the Sales Order (row identity, amount, timestamps) | derived |
| `subtotal`, `tax_total`, `discount_total`, `total` | ERPNext summary fields; shipping charge and consumed-credit deductions carved out of the tax fields, `total` = `grand_total` (the cart reconciliation) | derived |
| `gift_card_total`, `credit_line_total` | `Consumed` `Ceto Cart Credit Reservation` holds of the completed cart's Quotation (`CartCredits.consumed_credits`) | gap |
| `created_at`, `updated_at` | `Ceto Order Reference.creation` / `modified` | direct |

The money/address rows are the pinned Phase 6 serializer contract
(`ceto/services/orders/serialization.py`). The `customer_id` row describes the
**Phase 1 model**: today's serializer still reads the completed cart's
`Ceto Cart Reference.owner_customer`; once the snapshot column lands it reads
the order reference's effective owner (the snapshot, with the legacy cart
fallback above) instead — the contract is pinned here so that switch is a
serializer detail, never a contract change. Phase 0 creates neither the
column nor any endpoint.

## Status mapping

**Upstream contract fact:** `@medusajs/types@2.21.1` pins the unions —
`OrderStatus` = `pending | completed | draft | archived | canceled |
requires_action`, `PaymentStatus` = `not_paid | awaiting | authorized |
partially_authorized | captured | partially_captured | partially_refunded |
refunded | canceled | requires_action`, `FulfillmentStatus` =
`not_fulfilled | partially_fulfilled | fulfilled | partially_shipped | shipped
| partially_delivered | delivered | canceled`. What a server reports for a
placed order is **not** pinned — Medusa leaves status transitions
server-defined.

**Ceto decision:** until payment/fulfillment provider surfaces exist, Ceto
orders always report the pinned defaults `status: "pending"`,
`payment_status: "not_paid"`, `fulfillment_status: "not_fulfilled"` (the
`StoreOrder` model defaults in `ceto/types/http/store/orders/entities.py`).
ERPNext's own `Sales Order` status / `docstatus` (Draft → To Deliver and Bill
→ Completed on submission) is deliberately **not** projected onto them: the
ERPNext lifecycle answers fulfilment questions Ceto has not yet exposed, and
projecting it would invent transitions the pinned unions' semantics do not
license. The `list` `status` filter matches against this single reported
value, so filtering by any other `OrderStatus` member yields an empty page.

| Medusa order status | ERPNext / Ceto source | Classification |
|---|---|---|
| `status` | fixed `pending` (pinned model default; no transition engine yet) | gap |
| `payment_status` | fixed `not_paid` (payment provider surface deliberately absent) | gap |
| `fulfillment_status` | fixed `not_fulfilled` (fulfillment provider surface deliberately absent) | gap |
| ERPNext `Sales Order.status` / `docstatus` | no Medusa equivalent served — Ceto keeps the ERPNext lifecycle internal | gap |

## Authorization and ownership

**Upstream contract facts** (verified in `@medusajs/medusa@2.21.1`):

- The publishable API key is enforced for the whole `/store` namespace by the
  framework (`ensurePublishableApiKeyMiddleware`) — every orders route
  requires `x-publishable-api-key`.
- `GET /store/orders`, `POST …/transfer/request` and `POST …/transfer/cancel`
  run `authenticate("customer", ["session", "bearer"])` — a guest request is
  rejected before any handler runs.
- `GET /store/orders/{id}` carries **no** authentication middleware on
  purpose: the core route comment states the order id — "a UUID that requires
  brute forcing to gain access" — is the authentication mechanism, and points
  to the secure-order-retrieval guide for servers that want more.
- The transfer `accept`/`decline` routes also carry no customer
  authentication: the single-use transfer token in the body authorizes.
- The `list` handler forces `customer_id = req.auth_context.actor_id` (and
  `is_draft_order: false`) — a customer can only ever list their own orders;
  guest orders belong to no list.

**Ceto decisions:**

- **Effective ownership** is the `owner_customer` snapshot on the order's
  `Ceto Order Reference` (the Phase 1 model; Phase 0 records it and creates
  nothing): the completing transaction — the same locked completion that
  submits the Sales Order and debits the cart's credit holds — populates the
  snapshot atomically, so an order's owner is fixed at birth and afterwards
  independent of the immutable cart history. Ceto never re-derives ownership
  from the Sales Order's customer links (a guest checkout's Sales Order names
  the configured Guest Customer, which is not ownership evidence), and never
  reads ownership from the cart once the snapshot exists.
- **Legacy fallback and backfill**: references completed before the snapshot
  column exists (the Phase 6 records carry only `{order_id, sales_order,
  cart_id}`) resolve their effective owner from the completed cart's
  `Ceto Cart Reference.owner_customer` — the same Customer the Frappe
  `User` → `Contact` → `Customer` chain resolved at claim/completion time
  (carts Recorded Decision 3) — and a one-time backfill copies that value
  onto the order reference. The immutable cart history is only ever a
  fallback, never the live source; after the backfill nothing consults it.
- **Transfer acceptance writes the snapshot only**: accept — and an accepted
  `update_order_email` — update the `Ceto Order Reference` (`owner_customer`,
  optionally the reference's email) and nothing else. The completed cart's
  `Ceto Cart Reference.owner_customer` keeps the customer who completed the
  cart, and the Sales Order keeps its birth customer and contact lineage —
  the transfer is order-reference state, never a rewrite of cart history or
  ERPNext documents (Recorded Decisions 3 and 12).
- **Guest orders / ownership fallback**: a guest-placed order has
  `customer_id: null` and no owner. Its capability is the unguessable
  `order_…` id itself (upstream parity with the intentionally unauthenticated
  retrieve); it never appears in any `list` response, because the
  authenticated list is scoped to the caller's orders.
- **Order retrieval auth — the PRD's open question, resolved**: the
  preliminary orders goal language described order retrieval by authenticated
  customers and left the guest case open. Verification pinned upstream's
  retrieve as deliberately capability-based and guest-accessible (the core
  route's own comment above), and Phase 0 chooses exact compatibility: the
  unguessable id is the credential for whoever holds it, guest or
  authenticated — adding a customer-authentication gate would be an
  upstream-incompatible invention. This resolves the PRD's open
  authentication question by matching upstream exactly; the authenticated
  `list` stays strictly customer-scoped.
- The authenticated `list`/`transfer/request`/`transfer/cancel` routes
  resolve the session user to a Customer with the same resolver the cart
  claim uses (carts Recorded Decision 3); a user without exactly one Customer
  is `401 unauthorized`.
- A cancelled order is rejected upstream by every transfer route; Ceto has no
  order-cancellation surface yet, so Ceto mirrors the validation as pinned
  contract (it becomes live together with any future cancel surface).

## Publishable-key scope

**Upstream contract fact:** the publishable key selects the store's sales
channel; the pinned order routes do **not** scope order access by key.

**Ceto decision:** orders inherit the `region_id` / `sales_channel_id` scope
of the completed cart's reference (the serializer already reports both from
there), and every orders route checks the presented key's scope against it —
the same `CartPublishableKey.check_reference` values, applied to the order's
inherited scope. Because the orders surface is read-only/transfer-only, a
wrong-scoped key is masked as `404 not_found` (a foreign order simply does
not exist for that key) rather than the carts' mutation-time `403
not_allowed`; there is no mutation to refuse and nothing may leak through the
difference.

## List filters and stable ordering

**Upstream contract facts:**

- `StoreOrderFilters` pins exactly two domain filters, `id` and `status`,
  each a single value or a list (`status` over the pinned `OrderStatus`
  union); the server validator adds `$and`/`$or` combinators on top.
- Pagination rides `FindParams`: `fields` (`SelectParams`), `limit`,
  `offset`, `order` (sort expression), `with_deleted`; the server validator
  defaults to `offset: 0, limit: 50`.
- The response is the pinned `PaginatedResponse` envelope:
  `{orders, count, offset, limit}`. The shared `PaginatedResponse` type also
  declares an optional `estimate_count` field, but for this exact route and
  server (2.21.1) the orders list handler never emits it — no
  `estimate_count` appears anywhere in the pinned orders API implementation.
- **No default sort order is pinned anywhere** in the 2.21.1 packages — the
  `order` query parameter exists, but which ordering a server returns without
  it is server-defined.
- The retrieve-side `StoreGetOrderParams` is a bare `SelectParams` (`fields`
  only); upstream defaults return a much wider field/relation set for
  retrieve than for list.

**Ceto decisions:**

- **Stable list ordering**: `creation DESC, order_id ASC` — newest order
  first, with the public id as a total tiebreak so pagination is
  deterministic. This is a Ceto choice; upstream leaves the default order
  server-defined.
- The pinned list defaults are mirrored: `limit` 50, `offset` 0, and the
  pinned `{orders, count, offset, limit}` envelope (no `estimate_count` —
  Ceto has no index engine).
- Filters are the pinned `id` / `status` only. The `$and`/`$or` combinators,
  client `order` sort expressions and `with_deleted` (Ceto has no soft
  delete) are **rejected as `400 invalid_data`** instead of silently ignored
  — a client must never receive a page it cannot reproduce.
- `fields` behaves as on the cart routes (same `fields` selector
  implementation).

## Transfer lifecycle

**Upstream contract facts** (verified in `@medusajs/core-flows@2.21.1` and
`@medusajs/medusa@2.21.1`):

- **request** (authenticated customer): validates the order is not cancelled,
  the requesting customer has an account (`has_account`) and does not already
  own the order (both `invalid_data`). The ownership check compares the
  order's `customer_id` with the requester's id alone: upstream refuses only
  the customer who **already owns the order** — a claim against an order
  owned by **another** registered customer is accepted upstream. It creates a
  `transfer` order change
  in status `REQUESTED` whose `TRANSFER_CUSTOMER` action carries
  `details.token` (a UUID v4), `details.original_email` (the order's current
  email) and — with `update_order_email` — `details.new_email` (the
  requesting customer's email). It then emits `order.transfer_requested`
  with payload `{id, order_change_id}` and responds with the unchanged
  `{order}`.
- **Request semantics — the discovered contract**: the pinned
  `StoreRequestOrderTransfer` payload carries only `{description?,
  update_order_email?}` — **no recipient identifier of any kind**. A transfer
  request is therefore initiated by the authenticated customer who wants
  ownership *for themselves*: the pending `TRANSFER_CUSTOMER` change records
  that requesting customer, and acceptance applies `customer_id` to that
  stored requester (`@medusajs/order@2.21.1`
  `dist/utils/actions/transfer-customer.js`). Upstream ships no route by
  which a current owner nominates another named customer.
- **Token transport**: the pinned `token` field is documented in
  `@medusajs/types` as "The transfer token received in the email
  notification" — the token travels by email notification, never in an API
  response. The event payload carries no token; and the pinned core ships no
  transfer-email subscriber (its built-in configurable-notifications handler
  covers `order.created` only) — delivery is a notification-module /
  subscriber concern left to the server installation.
- **Upstream token storage**: upstream persists the plaintext token itself —
  on the pending order change's `TRANSFER_CUSTOMER` details — and relies on
  the notification layer to read it back out for delivery.
- **accept** (token-authorized): requires a `REQUESTED` transfer change for
  the order (`invalid_data` when absent) and an exact token match
  (`not_allowed` "Invalid token."). Confirming the change applies the pinned
  `TRANSFER_CUSTOMER` operation: `customer_id` becomes the requesting
  customer and, when `update_order_email` was requested, the order email
  becomes that customer's email.
- **decline** (token-authorized): same token match against an active
  (`PENDING`/`REQUESTED`) transfer change; marks the change declined —
  terminal.
- **cancel** (authenticated customer; no request body): requires an active
  transfer change; only the customer who requested the transfer may cancel
  it (`not_allowed` otherwise — admin actors exempt). The change is deleted,
  killing its token.
- **Lifetime / replay**: no expiry is defined anywhere in the pinned 2.21.1
  packages — upstream, a token lives exactly as long as its pending request.
  The lifecycle is terminal: after accept, decline or cancel no pending
  transfer remains, so any further accept is `invalid_data`, a further
  decline/cancel fails the active-change check, and a wrong token is always
  `not_allowed`. All four routes respond `{order}` afterwards.

**Ceto decisions:**

- **Transfer requester semantics (preliminary PRD superseded)**: the
  preliminary orders PRD assumed a current owner initiates a transfer to a
  named recipient customer. The verified contract above carries no recipient
  and upstream has no such route, so Ceto Phase 0 chooses the exact
  Medusa-compatible request semantics and this supersedes the PRD
  assumption: an authenticated customer requests a guest/unowned order for
  themselves; the pending `Ceto Order Transfer` record (Phase 1 model)
  stores that requesting customer; the token is delivered to the order's
  current email so the current holder — the person who placed the order —
  consents by accepting or declining; acceptance applies ownership to the
  requesting customer stored on the transfer, never to a payload-supplied or
  email-guessed recipient. Phase 0 registers no endpoint, so no behavior
  changes yet.
- **Eligible orders** are guest/unowned ones (effective owner null — the
  order reference's `owner_customer` snapshot, or its legacy cart fallback
  before backfill): the transfer moves such an order to the requesting
  customer. This is a **deliberately stricter Ceto decision**, not upstream
  parity: upstream's only ownership refusal is self-ownership (the fact
  above), so upstream accepts a transfer request against an order owned by
  another registered customer, while Ceto refuses such claims with the same
  `invalid_data` family and keeps the transfer a guest-order recovery flow.
  Transferring an already-owned order reproduces the upstream `invalid_data`
  refusal.
- **Token storage — digest only, never plaintext**: upstream stores the
  plaintext token on its pending order change (the fact above); Ceto
  deliberately hardens beyond that: the `Ceto Order Transfer` record
  persists only a SHA-256 digest of the token — the same hash-only
  discipline as the credit wallet's `code_hash` (carts Recorded Decision
  section, Promotion/credit mapping). The plaintext exists only inside the
  request that mints it: it is handed once to the
  `ceto_order_transfer_requested` hook for delivery and then discarded;
  accept and decline hash the presented token and compare digests. No
  plaintext token is ever stored, logged or returned by Ceto.
- **Recipient delivery**: the token is **never** returned by any API
  response. Ceto hands the plaintext once to the site through the
  `ceto_order_transfer_requested` hook (Frappe hook: order id, token,
  recipient email) so the site's own notification integration delivers it —
  Ceto ships no email provider. With no hook receiver registered the request
  simply stays pending until it is cancelled by its requester or expires.
- **Recipient**: the order's current email (upstream's `original_email`), so
  the person who placed the guest order is the one who can accept or decline.
- **Lifetime — 7 days (Ceto decision, not upstream parity)**: upstream
  defines no expiry (the fact above), so the 7-day lifetime is a Ceto
  decision and must never be presented as upstream parity: a pending
  transfer expires **7 days after its request was created**. Expired
  credentials return the same safe `not_allowed` family as any other failing
  token — no distinguishable expiry error exists, so nothing about the
  request's state can be probed through the difference — and an expired
  attempt never changes ownership. The requester can still cancel an expired
  request.
- **Replay**: consumed (accepted), declined, cancelled and expired
  credentials all fail closed — a consumed or wrong token is `not_allowed`,
  a missing pending request is `invalid_data`, matching the pinned error
  families.
- **`update_order_email`**: acceptance moves ownership to the requesting
  customer's Customer and records the new email on the order reference, which
  the serializer serves. The submitted ERPNext Sales Order is **never**
  modified — see Recorded Decision 12.

## Deliberate omissions

Carried over from the carts mapping (Recorded Decisions there) and pinned for
the orders surface:

- `display_id` / `custom_display_id` (orders Recorded Decision 1 here, carts
  Recorded Decision 9): Medusa's sequential display numbers have no ERPNext
  equivalent.
- `version`, `summary`, `transactions`, `payment_collections`,
  `fulfillments`, `customer`: provider surfaces that do not exist in Ceto
  yet.
- The pinned `item_discount_total` / `shipping_discount_total` split: ERPNext
  carries a single order-level `discount_amount`, so the split cannot be
  derived without inventing numbers (`discount_total` keeps the order-level
  amount).
- `estimate_count` on the list envelope: the orders list route never emits it
  (pinned 2.21.1 upstream included) — Ceto has no index engine to add one.
- The list's `$and`/`$or` combinators, `order` sort expressions and
  `with_deleted`: deliberately unsupported (see Recorded Decision 8).
- Draft orders (`is_draft_order: false` upstream): every Ceto order is a
  placed order; Ceto has no draft-order surface to exclude.

## Recorded Decisions

1. **Order identity** — the public id is Ceto's `order_…` id on the
   `Ceto Order Reference`; the ERPNext Sales Order name stays internal to the
   mapping and is never serialized.
2. **Effective ownership** — an order's owner is the `owner_customer`
   snapshot on its `Ceto Order Reference` (Phase 1 model): the completing
   transaction populates it atomically, ownership is independent of the
   immutable cart history from birth on, and Ceto never re-derives ownership
   from Sales Order customer links or copies it back onto the cart.
3. **Legacy ownership fallback** — references completed before the snapshot
   column exists resolve their effective owner from the completed cart's
   `Ceto Cart Reference.owner_customer` and are backfilled onto the order
   reference once. The immutable cart history is only ever a fallback, never
   the live source: after the backfill — or for every reference born with the
   snapshot — the cart is not consulted.
4. **Guest orders / capability retrieval (PRD question resolved)** — a
   guest-placed order has `customer_id: null` and no owner: the unguessable
   `order_…` id is the capability (upstream parity with the intentionally
   unauthenticated retrieve), and no `list` response ever contains it. Phase
   0 keeps exact upstream compatibility, which resolves the preliminary
   PRD's open retrieval-authentication question even though its goal
   language referred to authenticated customers.
5. **Publishable-key scope** — every orders route requires the key; scope is
   inherited from the completed cart and a wrong-scoped key is masked as
   `404 not_found`, never `403` (read-only surface, nothing to refuse).
6. **Status defaults** — orders report the pinned `pending` / `not_paid` /
   `not_fulfilled` defaults until payment and fulfillment provider surfaces
   exist; ERPNext's own status lifecycle is not projected onto the Medusa
   unions.
7. **Stable list ordering** — Ceto lists orders `creation DESC, order_id ASC`
   (newest first, deterministic tiebreak); upstream pins no default sort, so
   this is a Ceto choice clients may rely on.
8. **List query surface** — filters are the pinned `id` / `status` only, with
   the upstream pagination defaults (`limit` 50, `offset` 0) and the pinned
   `{orders, count, offset, limit}` envelope; `$and`/`$or`, client `order`
   expressions and `with_deleted` are rejected as `400 invalid_data` rather
   than ignored.
9. **Transfer requester semantics (PRD superseded)** — the pinned
   `StoreRequestOrderTransfer` payload carries no recipient identifier, so a
   transfer is initiated by the authenticated customer seeking ownership of a
   guest/unowned order for themselves; the pending transfer stores that
   requesting customer, the token is delivered to the order's current email
   for consent, and acceptance applies ownership to the requesting customer
   recorded on the transfer. This supersedes the preliminary PRD assumption
   that an owner nominates a named recipient customer; Phase 0 registers no
   endpoint.
10. **Transfer token transport & digest-only storage** — the token is never
    in an API response; Ceto hands the plaintext once to the
    `ceto_order_transfer_requested` hook (order id, token, recipient email)
    and then discards it. Only a SHA-256 digest is persisted on the
    `Ceto Order Transfer` record: upstream stores the plaintext token on its
    pending order change, and Ceto deliberately hardens beyond that. Ceto
    ships no email provider.
11. **Transfer token lifetime & replay** — upstream defines no expiry; Ceto
    pins a 7-day lifetime from request creation as an explicit Ceto decision
    — a deliberate Ceto addition, never upstream behavior. Expired tokens
    fail with the same safe `not_allowed` family as wrong ones and change no
    ownership; a consumed or wrong token is `not_allowed`, a missing pending
    request is `invalid_data`.
12. **Immutable Sales Order, transfer write scope** — an accepted
    `update_order_email` records the new email on the order reference (served
    from there by the serializer); acceptance writes only the order
    reference's `owner_customer`/email — never the completed cart's
    `Ceto Cart Reference.owner_customer` and never the Sales Order's
    customer/link lineage; submitted ERPNext documents are never mutated by
    the transfer flow.
13. **No Custom Fields** — every order field without an ERPNext equivalent is
    classified **gap** and handled by Ceto compatibility doctypes/behavior
    only (carried over from the carts mapping).

## Phase 0 boundary

- The manifest (`ceto/types/http/store/orders/manifest.py`) and the pinned
  `StoreOrder` entities are the only code; `ceto.api.routes` wires no order
  module, and `ceto.tests.types.http.store.test_orders_manifest` fails if
  that changes. The Phase 1 artifacts this document pins — the
  `owner_customer` snapshot on `Ceto Order Reference`, the `Ceto Order
  Transfer` record with its token digest, and the serializer's
  effective-owner read — are deliberately **not** created here: no schema, no
  endpoint, no behavior change.
- The README's Orders table stays ⚪️ To implement; the README-drift test
  keeps the advertised table and the manifest identical.
- The implementation phase adds the handlers and turns this document's
  Ceto decisions into the route/service behavior, mirroring the carts
  pattern (manifest → endpoints/services → registry equality test).
