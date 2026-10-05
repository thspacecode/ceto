# Orders Phase 5 — Transfer Accept and Decline (plan)

Phase 5 turns the two remaining contract-only transfer routes from the pinned
Phase 0 surface into implemented, registered behavior:

- `POST /store/orders/{id}/transfer/accept` (`StoreAcceptOrderTransfer`,
  pk + transfer token)
- `POST /store/orders/{id}/transfer/decline` (`StoreDeclineOrderTransfer`,
  pk + transfer token)

Both routes act on the pending `Ceto Order Transfer` record created by the
Phase 4 request route. Semantics, token handling and state transitions follow
the **upstream contract facts** and **Ceto decisions** already recorded in
[Phase 0](field-mapping.md) (see the *Transfer lifecycle* section); this note
only scopes the phase — it pins no new contracts.

## Scope

1. **Token-authorized dispatch** — both routes resolve the pending transfer
   from the token supplied by the caller, not from the session customer;
   publishable-key auth with the transfer token, no customer session.
2. **accept** — consumes the token once, applies ownership to the requesting
   customer stored on the transfer (never a payload-supplied recipient),
   closes the transfer as accepted and returns the updated `{order}`.
3. **decline** — consumes the token once, closes the transfer as declined and
   returns the unchanged `{order}`.
4. **Expiry and single-use** — a token past its 7-day window, or already
   consumed, is rejected the same way as an unknown token; only the SHA-256
   digest is ever compared or persisted.
5. **Hooks** — the completion hooks fire with the same payload shape as the
   Phase 4 lifecycle hooks.

## Non-goals

- No new routes beyond the two above; the manifest registry stays at the
  pinned six routes and the Phase 4 registry test must keep passing.
- No changes to request/cancel behavior delivered in Phase 4.

## Status

Plan committed as the phase boundary marker on `feat/orders-phase-5`;
implementation commits follow on this branch. The PR is opened as a **draft**
stacked on `feat/orders-phase-4` and is marked ready only when the routes are
registered and the tests above pass.
