"""True end-to-end journeys across the dispatched Ceto Store API.

The per-surface suites under ``ceto.tests.api`` and ``ceto.tests.services``
pin each route and service in isolation; the modules here walk one coherent
customer story through the real router on the test site — registration to a
replayed order — plus the cross-surface boundary hardening no single surface
can prove on its own.
"""
