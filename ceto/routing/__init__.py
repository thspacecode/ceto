"""Medusa-compatible HTTP routing for Ceto."""

from ceto.routing.router import Router

store_router = Router(prefix="/store")

# Populate the application route registry whenever the routing package loads.
from ceto.api.auth import customer as customer_routes  # isort: skip

__all__ = ["Router", "store_router"]
