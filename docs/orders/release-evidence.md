# Store Orders — Route Map and Release Evidence (Phase 6)

The mechanical companion to [Phase 0](field-mapping.md): where each of the six
pinned order routes lives, which service it calls, which HTTP contracts it
speaks, what authorizes it, and which tests hold it in place — closing with
the Phase 6 release validation facts. This note pins no new contracts; it maps
the shipped surface.

## Shared plumbing

Every route rides the same pieces, so the per-route rows stay small:

- **Publishable key** — `CartPublishableKey.from_request`
  (`ceto/api/store/publishable_key.py`) resolves and requires
  `x-publishable-api-key` on all six routes; a missing key is
  `401 unauthorized` before any handler logic runs.
- **Facade** — `OrderService` (`ceto/services/orders/service.py`) is the only
  entry point the adapters see. It composes `OrderAccess` (masked resolution
  under key scope), `OrderListing` (the page read model, scoped by the
  `OrderOwnership` effective-owner chain through `OrderPageContext`),
  `OrderTransfer` (the row-locked lifecycle and its
  `ceto_order_transfer_requested` / `ceto_order_transfer_accepted` /
  `ceto_order_transfer_declined` hooks) and `OrderSerializer` (the canonical
  `StoreOrder` JSON, narrowed by the shared `select_fields`).
- **Session identity** — the customer-authenticated routes resolve the session
  user with `CartCustomers.resolve` (`ceto/services/carts/customers.py`); the
  transfer requester's email derives from the same session
  (`_session_requester_email`), never from a payload.
- **Registration** — all six adapters are functions in
  `ceto/api/store/orders.py`, imported once by `ceto/api/routes.py`;
  `ORDER_ROUTES` (`ceto/types/http/store/orders/manifest.py`) pins the same
  six contracts and the README's Orders table mirrors them.

## Route map

Row numbers match the pinned contract table in [Phase 0](field-mapping.md).
Request/response types live under `ceto/types/http/store/orders/`
(`payloads.py`, `queries.py`, `responses.py`); every response is the exact
pinned `StoreOrderResponse` (or `StoreOrderListResponse`) and never carries a
token or the internal Sales Order identity.

| # | Route | Adapter | `OrderService` → | HTTP contract types | Authorization and scope |
|---|---|---|---|---|---|
| 1 | `GET /store/orders/{id}` | `retrieve_order` (guest-dispatchable) | `retrieve` → `OrderAccess.resolve` + `OrderSerializer` + `select_fields` | query: `StoreGetOrderParams` shape (`fields` only) · response: `StoreOrderResponse` | Publishable key + the unguessable `order_…` id as the capability — no customer gate; unknown id, broken lineage and a wrong-scoped key are all the same masked `404 not_found` |
| 2 | `GET /store/orders` | `list_orders` | `list` → `OrderListing` (via `OrderOwnership` / `OrderPageContext`) | query: `StoreOrderFilters` (`id` / `status` / `limit` / `offset` / `fields`) · response: `StoreOrderListResponse` (`{orders, count, offset, limit}`) | Publishable key + customer session; the owner scope is forced server-side (never a client-supplied `customer_id`) and the key scope filters the page instead of masking |
| 3 | `POST /store/orders/{id}/transfer/request` | `request_order_transfer` | `request_transfer` → `OrderTransfer.request` | payload: `StoreRequestOrderTransfer` (strict) · response: `StoreOrderResponse` | Publishable key + customer session; the requester is the authenticated customer (session-derived identity and email, never payload data); guest-only eligibility and one live pending request under the reference row lock |
| 4 | `POST /store/orders/{id}/transfer/accept` | `accept_order_transfer` (guest-dispatchable) | `accept_transfer` → `OrderTransfer.accept` | payload: `StoreAcceptOrderTransfer` (strict, `token` required) · response: `StoreOrderResponse` | Publishable key + the single-use transfer token — digest-only compare, no customer session; every failing credential (wrong, expired, replayed, declined) is the same `403 not_allowed` `Invalid token.`, a missing pending request is `400 invalid_data` |
| 5 | `POST /store/orders/{id}/transfer/cancel` | `cancel_order_transfer` | `cancel_transfer` → `OrderTransfer.cancel` | no body (`request_type: None`) · response: `StoreOrderResponse` | Publishable key + customer session; only the record's `requested_by` may cancel (`403 not_allowed` otherwise); a missing or replayed cancel is `400 invalid_data`; the delete destroys the digest-only token with it |
| 6 | `POST /store/orders/{id}/transfer/decline` | `decline_order_transfer` (guest-dispatchable) | `decline_transfer` → `OrderTransfer.decline` | payload: `StoreDeclineOrderTransfer` (strict, `token` required) · response: `StoreOrderResponse` | Publishable key + the single-use transfer token, exactly as accept; the refusal closes the record `Declined` and writes nothing else |

## Rollback and concurrency tests

Every write path locks the `Ceto Order Reference` row before any check reads
state, mutates inside that lock, and fires its hook inside the transaction —
a receiver failure rolls the whole write back. The proving tests:

| Path | Suite | Concurrency / rollback proof |
|---|---|---|
| request | `ceto.tests.services.orders.test_transfer_request` | `test_a_second_request_while_pending_is_refused`, `test_an_expired_request_is_superseded_by_a_fresh_one`, `test_a_failing_receiver_fails_the_request_and_rolls_the_insert_back` |
| accept | `ceto.tests.services.orders.test_transfer_accept` | `test_a_wrong_token_is_not_allowed_without_mutation`, `test_a_replayed_accept_fails_as_not_allowed`, `test_the_hook_fires_inside_the_transaction_after_the_writes`, `test_a_failing_receiver_fails_the_accept_and_rolls_the_writes_back` |
| decline | `ceto.tests.services.orders.test_transfer_decline` | `test_a_replayed_decline_fails_as_not_allowed`, `test_the_declined_hook_fires_inside_the_transaction_after_the_write`, `test_a_failing_receiver_fails_the_decline_and_rolls_the_write_back` |
| cancel | `ceto.tests.services.orders.test_transfer_cancel` | `test_a_replayed_cancel_fails_as_missing_pending`, `test_an_error_at_the_delete_leaves_the_record_untouched` |
| visibility | `ceto.tests.services.orders.test_transfer_visibility` | `test_acceptance_moves_list_visibility_to_the_recorded_requester` — one real transfer proven through both read surfaces |

The read paths (retrieve, list) write nothing, so they carry no rollback
tests; the router-level net beneath every route is
`ceto.tests.routing.test_router::test_error_response_rolls_back_partial_writes`.

## Regression and route-manifest tests

- **Manifest / README drift** —
  `ceto.tests.types.http.store.test_orders_manifest`:
  `test_manifest_covers_exactly_the_6_pinned_routes`,
  `test_phase_5_registers_all_six_pinned_routes`,
  `test_readme_orders_table_matches_the_manifest`,
  `test_readme_marks_exactly_the_registered_surface_implemented`.
- **Runtime registry equality** —
  `ceto.tests.routing.test_router::test_implemented_order_routes_match_the_phase_5_slice`
  compares the live router registry against the manifest.
- **API surfaces** — `ceto.tests.api.store.test_orders` (retrieve),
  `ceto.tests.api.store.test_orders_list` (list) and
  `ceto.tests.api.store.test_orders_transfers` (the four transfer routes,
  including `test_the_transfer_routes_are_registered_exactly_once`).
- **Service behavior** — `ceto.tests.services.orders`: `test_access`,
  `test_retrieval`, `test_serialization`, `test_listing`, `test_ownership`
  and the five `test_transfer_*` suites.
- **Contract types** — `ceto.tests.types.http.store.test_orders_entities`,
  `test_orders_payloads`, `test_orders_queries`, `test_orders_responses`.
- **Persistence** — `ceto.tests.test_persistence_indexes` pins the schema
  indexes; `ceto.tests.doctype.test_ceto_order_reference` and
  `ceto.tests.doctype.test_ceto_order_transfer` prove the uniqueness
  behavior beneath them.
- **Documentation** — `ceto.tests.docs.test_orders_field_mapping` fails on
  drift between the code, the README and `field-mapping.md`.

## Release validation (authoritative latest run)

Recorded facts from the closing Phase 6 run, on the unchanged baseline
`test_site` configuration (`allow_tests` true only — the suite self-manages
the user-creation throttle, so no `site_config.json` edits):

- **Full suite** — 729 tests, passed twice (repeat run for determinism).
- **pre-commit** — passed (`--all-files`: ruff lint + format, hygiene hooks).
- **semgrep** — 76 rules over 115 targets, 0 findings.
- **pip-audit (project mode)** — no known vulnerabilities in the declared
  dependency closure at the current CI resolution: the job
  (`pip-audit --desc on .`) resolves `pyproject.toml` fresh, installing
  PyJWT 2.15.x under the hardened floor `PyJWT>=2.15.0,<3` (re-confirmed
  after the raise). Floor evidence from per-pin pip-audit runs: PyJWT
  2.13.0 carries 14 advisories (12 are no longer detected in 2.14.0;
  `PYSEC-2026-4141` and `PYSEC-2026-4183` are fixed in 2.15.0), 2.14.0
  still carries those two, and
  2.15.0 is clean — 2.15.0 is the first audit-clean compatible release. The
  job audits the app's declared closure, not the shared bench runtime;
  advisories on that environment's installed packages are operational
  concerns outside this repo.
- **Indexes pinned** — `ceto.tests.test_persistence_indexes` holds the
  schema-level net over the audited read paths (Phase 6 scope item 1).
- **README** — the Orders table already marks all six routes Implemented,
  pinned to the registered surface by the README-drift tests.

Still outstanding, deliberately not claimed landed: the one-line CI
permissions hardening on `.github/workflows/ci.yml` — see the blocked note in
[phase-6.md](phase-6.md).
