# Store Payments — Medusa → ERPNext Field Mapping (Phase 5, slices 5A–5D)

Classification legend for every mapping row:

- **direct** — the Medusa field maps 1:1 onto a Ceto/ERPNext field (possibly
  with type coercion).
- **derived** — the Ceto field is computed from one or more Medusa fields or
  Ceto configuration.
- **gap** — no ERPNext equivalent exists; handled by a Ceto compatibility
  layer (Ceto doctypes / behavior), **not** by Custom Fields on core ERPNext
  doctypes.

Phase 5 slices 5A/5B pin the Medusa 2.21.1 payment contracts and build the
Ceto-side persistence, provider registry and payment policy. Slices 5C/5D
serve the pinned route surface (see
[endpoints.md](./endpoints.md)), integrate paygi's `create_payment` through a
narrow privileged boundary, wire the enforced/off payment policy into cart
completion and project the authoritative payment state onto the cart and
order serializations.

## Pinned Contracts

Source of truth: <https://docs.medusajs.com/api/store/payment-collections> and
<https://docs.medusajs.com/api/store/payment-providers>. Compatibility layer:
`@medusajs/js-sdk@2.21.1`; request/response type names from
`@medusajs/types@2.21.1`; route set, middlewares and validators verified
against `@medusajs/medusa@2.21.1`. Manifest: `ceto/types/http/store/payments/
manifest.py` (pure Python, contract-only).

| Medusa route | HttpTypes | Response | SDK | Auth |
|---|---|---|---|---|
| `POST /store/payment-collections` | `StoreCreatePaymentCollection` | `StorePaymentCollectionResponse` | — (inlined in `initiatePaymentSession`) | publishable-key+optional-session |
| `POST /store/payment-collections/{id}/payment-sessions` | `StoreInitializePaymentSession` | `StorePaymentCollectionResponse` | `initiatePaymentSession` | publishable-key+optional-session |
| `GET /store/payment-providers` | query (`region_id` required, limit 20 / offset 0) | `StorePaymentProviderListResponse` | `listPaymentProviders` | publishable-key |

Pinned status unions (Phase 5 subsets in `ceto/types/http/store/payments/
entities.py`):

- `PaymentCollectionStatus` — `not_paid | awaiting | authorized |
  partially_authorized | canceled | completed | failed`
- `PaymentSessionStatus` — `pending | pending_authorization | authorized |
  captured | requires_more | error | canceled`

## Payment Collection → Ceto Payment Collection

| Medusa `StorePaymentCollection` field | Ceto `Ceto Payment Collection` field | Classification |
|---|---|---|
| `id` (`pay_col_…`) | `payment_collection_id` (document name; `pay_col_` + 128 crypto bits) | gap |
| — (cart relation) | `cart_reference` → `Ceto Cart Reference`, unique: one collection per cart lifetime | gap |
| `currency_code` | `currency_code` (lowercase ISO 4217, from the cart's `Quotation.currency`) | derived |
| `amount` | `amount` (the cart's current `Quotation.grand_total`) | derived |
| `status` | `status` (pinned Select; `not_paid` at creation, `completed` exactly when the current session captures, reset to `not_paid` when a fresh session replaces the live one) | direct |
| `payment_sessions[]` | `Ceto Payment Session` rows linked by `payment_collection`, oldest first | gap |
| `payment_providers[]` | the distinct `provider_id`s of the collection's sessions, resolved live through the Ceto provider registry | derived |
| `authorized_amount` / `captured_amount` | the current session's amount when its status proves money (`authorized`/`captured`), else `null` | derived |
| `refunded_amount`, `payments[]` | no refund flow exists; always `null` / omitted | gap |
| `metadata`, `completed_at` | not derivable without a capture ledger; always `null` | gap |
| — (cart embedding) | `StoreCart.payment_collection` via `PaymentSerializer.for_cart` (`null` when the cart holds none) | derived |

## Payment Session → Ceto Payment Session

| Medusa `StorePaymentSession` field | Ceto `Ceto Payment Session` field | Classification |
|---|---|---|
| `id` (`payses_…`) | `payment_session_id` (document name; `payses_` + 128 crypto bits) | gap |
| — (collection relation) | `payment_collection` → `Ceto Payment Collection` | gap |
| `provider_id` | `provider_id` (pinned registry id, `pp_…`) | direct |
| `amount`, `currency_code` | `amount`, `currency_code` — the per-attempt payable snapshot idempotent creation keys on | direct |
| `data` | `provider_data` (JSON object): the paygi attempt's owner response (`payment_id`, `provider_payment_id`, `status`, `amount_minor`, `currency`, `action_type`, `action_expires_at`, `checkout_url`) | direct |
| `status` | `status` (pinned Select; starts `pending`; `captured` exactly once via the paygi success hook, `error`/`canceled` from a terminal attempt status) | direct |
| `context`, `authorized_at` | no authorize flow exists; always `null` | gap |
| — (current-ness) | `is_current` — exactly one current session per collection | gap |

## Payment Provider → Ceto provider registry → paygi

| Medusa `StorePaymentProvider` field | Ceto backing | Classification |
|---|---|---|
| `id` (`pp_beam_beam`) | `PaygiProvider("beam", "Beam Settings")` — reads paygi's enabled switch | gap |
| `id` (`pp_stripe_stripe`) | `PaygiProvider("stripe", "Stripe Settings")` — reads paygi's enabled switch | gap |
| (list is region-scoped upstream) | `GET /store/payment-providers` answers with every enabled provider; the required `region_id` is publishable-key-scope-checked, but provider scoping *per region* waits for a Region surface | derived |

## The paygi charge boundary → `Payment Attempt`

The provider charge is one function — `ceto.services.payments.gateway.
create_payment` — between Ceto's session and paygi's `create_payment` API:

| Concern | Ceto boundary behavior | Classification |
|---|---|---|
| Reference | `reference_doctype: "Ceto Payment Session"`, `reference_name`: the `payses_…` id — paygi's success webhook walks this reference back to the session | derived |
| Idempotency | the paygi `idempotency_key` *is* the session id; a repeated creation request resolves the same `Payment Attempt`, never a second charge | derived |
| Minor units | exact `Decimal` conversion of the session's major-unit amount over ERPNext `Currency.fraction_units` (satang/fils/…); an ambiguous amount (excess precision, non-positive) refuses the charge | derived |
| Privilege | paygi requires a signed-in reader of the reference; the wrapper alone elevates to the trusted persistence scope, after the publishable key, cart scope and ownership checks have run | gap |
| Absence / failure | paygi missing, unreachable or failing collapses to "no charge" (logged): the session stays `pending` with empty `data`, the route answers `200` — never an accidental `500` | gap |
| Terminal statuses | attempt `Succeeded` → session `captured` (exactly once) and collection `completed`; `Failed` → session `error`; `Canceled` → session `canceled`; in-flight states keep the session `pending` | derived |

## Payment Policy → `ceto_cart.payment_policy` → completion

| Policy concern | Ceto backing | Classification |
|---|---|---|
| `ceto_cart.payment_policy` site config | `ceto.services.payments.policy.resolve_payment_policy()` | derived |
| `off` (default) | the `ceto_cart_payment_readiness` hook answers "no opinion" without reading payment rows; completion's gate stays open (backward compatible) | direct |
| `enforced` | the hook decides, failing closed: completion needs the cart's collection to carry a *current* session that is `authorized`/`captured`, matching the cart's live payable (amount + currency), for a provider that still resolves enabled; missing/stale/unpaid/mismatched or any check failure refuses | derived |

## Order payment_status projection

| Session state of the cart's current session | `StoreOrder.payment_status` | Classification |
|---|---|---|
| `captured` | `captured` | direct |
| `authorized` | `authorized` | direct |
| `pending`, `pending_authorization`, `requires_more`, `error`, `canceled` | `not_paid` (no proven money — no fabricated in-between state) | derived |
| no collection / no current session (stale or absent) | `not_paid` (pinned default) | derived |

`StoreOrder.payment_collections` embeds the completed cart's collection (the
same serialization the cart serves), or stays empty when the cart never
created one.

## Recorded Decisions

1. **paygi stays unchanged.** Ceto owns a provider registry in
   `ceto.services.payments.providers`; paygi's DocTypes, controllers and API
   are read-only to Ceto. No Ceto field, hook or patch touches paygi.
2. **Provider ids follow Medusa's `pp_<gateway>_<gateway>` convention.**
   `pp_beam_beam` and `pp_stripe_stripe` are the whole provider identity the
   store API serves — matching the pinned `StorePaymentProvider` (an `id`
   only).
3. **The paygi adapter is defensive.** A site without paygi installed, or
   without the settings tables, has no enabled providers — never a crash.
   Any failure reading a settings row is reported as "disabled": a payment
   provider read must never fail open.
4. **Payment policy fails closed.** `ceto_cart.payment_policy` accepts
   `off` / `enforced` (case- and whitespace-insensitive); unset or blank is
   the backward-compatible `off`; an unknown value or a broken
   `ceto_cart` section resolves to `enforced` — a config typo may only make
   checkout stricter, never looser.
5. **Session creation is idempotent on provider + cart + current payable.**
   Repeating a creation request with the same provider while the cart's
   amount and currency are unchanged returns the collection's current
   `pending` session untouched — no duplicate rows, no new ids.
6. **A changed payable or provider makes the old session stale.** The stale
   session (`is_current` 0) is kept as a history row and a fresh current
   session is booked for the new keys; the collection's status returns to
   `not_paid` with it. Only a `pending` session is reusable; a session that
   left `pending` is never handed out again. At most one current session
   exists per collection — enforced by the DocType validate.
7. **One collection per cart.** `Ceto Payment Collection.cart_reference` is
   unique, mirroring Medusa's own upsert semantics (an existing cart
   collection is returned, never duplicated). The collection's
   `amount` / `currency_code` track the cart's *current* payable; the
   sessions carry the per-attempt snapshots.
8. **The pinned three-route surface is served and masked.** All three
   routes are guest-dispatchable with no customer authentication (the
   session workflow picks up the authenticated customer's carts through the
   ownership rules) and require the publishable key; unknown or foreign
   carts and collections mask as `404 not_found`, unknown or disabled
   providers as `400 invalid_data` — nothing payment-shaped leaks.
9. **Money follows the StoreCart convention: plain floats, no minor units.**
   The conversion to paygi's integer `amount_minor` happens inside the
   gateway boundary — exact `Decimal` math over the currency master's
   `fraction_units`, refusing ambiguous amounts — never in the persisted
   mapping.
10. **A zero-payable cart has no payment session.** Session creation refuses
    carts with no amount payable (paygi gateways require a positive
    `amount_minor`); free checkouts skip the payment step entirely, so the
    storefront never needs a session for them.
11. **The paygi boundary is narrow and privileged.** Exactly one function
    calls paygi's `create_payment`; it elevates to the trusted persistence
    scope (paygi demands a signed-in reader of the reference) only after
    the route's publishable-key, cart scope and ownership checks have run,
    and it keys the charge's idempotency on the session id, referencing the
    session so captures find their way back.
12. **Provider absence and failure are stable, never an accidental 500.**
    The boundary answers "no charge" and logs; the session stays `pending`
    with empty `data` and the route answers with it. A client retry books a
    fresh attempt instead of raising.
13. **Capture is exactly-once, through paygi's verified success hook.** The
    `paygi_payment_succeeded` hook captures the referenced session once (a
    session already or no longer captureable is untouched) and completes
    the collection only when the captured session is still its current one;
    a stale captured session is history, and the enforced completion gate
    keeps refusing until the live session is paid.
14. **Projections report proven money only.** `authorized_amount` /
    `captured_amount` derive from the current session's status;
    `StoreOrder.payment_status` is `captured`/`authorized` exactly when the
    current session says so and `not_paid` otherwise — never a fabricated
    `awaiting`/`partially_*`.

## Demonstrated Phase 5 (5A–5D) behavior

- The pinned manifest and entities are contract-tested standalone
  (`ceto.tests.types.http.store.test_payments_manifest` /
  `test_payments_entities`).
- The DocTypes pin public-id naming, uniqueness, the single-current-session
  invariant and the pinned status unions (`ceto.tests.doctype.
  test_ceto_payment_collection` / `test_ceto_payment_session`).
- The registry, the defensive paygi adapter and the policy parser are tested
  without depending on site configuration
  (`ceto.tests.services.payments.test_providers` / `test_policy`).
- Idempotent session creation and the staleness semantics run against real
  cart fixtures (`ceto.tests.services.payments.test_collections`).
- The gateway boundary (minor units, stable failure, gateway naming), the
  session orchestration, the capture synchronization and the completion
  readiness gate have their own service suites
  (`ceto.tests.services.payments.test_gateway` / `test_sessions` /
  `test_synchronization` / `test_readiness` / `test_serialization`).
- The HTTP surface — authentication, strict query/body, masking, the
  paygi-backed happy path and its stable failures — is exercised through
  the real router (`ceto.tests.api.store.test_payments`).
