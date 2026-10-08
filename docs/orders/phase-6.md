# Orders Phase 6 — Hardening and Release (plan)

Phase 6 closes the orders epic. Phases 0–5 delivered and pinned the full
six-route surface (list, retrieve, and the transfer request / cancel / accept /
decline lifecycle); this phase changes no behavior and registers no routes. It
audits the shipped surface and lands only the hardening the release needs, per
the contracts already recorded in [Phase 0](field-mapping.md) — this note pins
no new contracts.

## Scope

1. **Persistence audit** — the order list (`OrderListing`) and the transfer
   lifecycle (`OrderTransfer`) query paths are verified against the live
   schema: every filter, join and credential column is indexed, and a
   schema-level test pins those indexes so a dropped `search_index` / `unique`
   flag fails in CI, not in production.
2. **Release documentation** — this note and a repository security policy.
3. **CI / security tooling** — the test workflow runs with a least-privilege
   `GITHUB_TOKEN` (the linter workflow already does); pre-commit, ruff and
   semgrep coverage confirmed in place.
4. **Dependency audit setup** — the `pip-audit` job confirmed in place and
   Dependabot (pip + GitHub Actions) enabled so dependency updates arrive
   continuously instead of only at audit time.

## Persistence audit (order list and transfers)

Read paths and the schema guarantees they ride:

- **`GET /store/orders` (count + page)** — filters
  `Ceto Order Reference.owner_customer` (indexed; the effective-owner scope)
  with the `Ceto Cart Reference` join and the key-scope filters
  `region_id` / `sales_channel_id` (both indexed); the page join rides the
  references' unique `cart_id` / `sales_order` indexes and the cart /
  quotation primary keys. Page ordering (`creation DESC, order_id ASC`) sorts
  one customer's already-scoped rows, so no composite index is warranted.
- **Retrieve / transfer resolution** — primary-key lookups: the public ids
  name the documents (`order_id`, `cart_id`, `transfer_id` via
  `autoname: field:`), and `Quotation` / `Sales Order` are ERPNext tables this
  app does not own.
- **`Ceto Order Transfer` scans** — the pending and terminal-digest scans
  filter by `order_reference` (indexed) and close few rows per order;
  `requested_by` is indexed for the cancel gate and `token_hash` is uniquely
  indexed — the digest-only credential cannot collide across orders.
- **Uniqueness** — one order per cart, one order per Sales Order, one digest
  per token are schema constraints; the doctype suites prove the behavior and
  Phase 6 adds the index-level net beneath them.

## Non-goals

- No behavior changes to the six pinned routes; the Phase 4 registry test and
  the Phase 0 contract tests must keep passing untouched.
- No new routes, fields or schema changes — the audit found the indexes in
  place; the deliverable is pinning and documentation, not migration.

## Status

Release-ready on `feat/orders-phase-6` — every Phase 6 deliverable has landed.
Final validation from the authoritative latest run, on the unchanged baseline
`test_site` configuration (`allow_tests` true only — the suite self-manages
the user-creation throttle, so the site needs no `site_config.json` edits):

- **Full suite** — 729 tests, passed twice (repeat run for determinism).
- **pre-commit** — passed (`--all-files`: ruff lint + format, hygiene hooks).
- **semgrep** — 76 rules over 115 targets, 0 findings.
- **pip-audit** — no known vulnerabilities.
- **Indexes pinned** — `ceto.tests.test_persistence_indexes` holds the
  schema-level net over the audited read paths.
- **README** — the Orders table already marks all six routes Implemented,
  pinned to the registered surface by the README-drift tests.

Landed in this phase: Dependabot setup (pip + GitHub Actions), the repository
security policy, the persistence-index schema test
(`ceto.tests.test_persistence_indexes`), the user-creation throttle guard in
`ceto.tests.services.carts.test_privileged_scope`, and the release-evidence
route map (`docs/orders/release-evidence.md`).

Blocked (still outstanding — **not** landed from this branch): the
least-privilege CI token — the branch's push credential is a GitHub App
installation without the `workflows` permission, so it may not create or
update `.github/workflows/ci.yml`; the one-line change ships out of band:

```yaml
# .github/workflows/ci.yml, after `pull_request:` in `on:`
permissions:
  contents: read
```

