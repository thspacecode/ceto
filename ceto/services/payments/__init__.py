"""Payment domain services (Phase 5 groundwork).

The store payment routes are not served yet; these modules own the pieces
the routes will call: the payment policy parser (``ceto_cart.
payment_policy``), the provider protocol/registry with the built-in
defensive paygi adapter, and the idempotent payment collection/session
persistence behind the pinned Medusa contracts.
"""
