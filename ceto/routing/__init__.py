"""Medusa-compatible HTTP routing for Ceto."""

from ceto.routing.response import JSON, JSONModel
from ceto.routing.router import Router

store_router = Router(prefix="/store")

# Populate the application route registry whenever the routing package loads.
from ceto.api.auth import customer as customer_routes  # isort: skip

__all__ = ["JSON", "JSONModel", "Router", "store_router"]
