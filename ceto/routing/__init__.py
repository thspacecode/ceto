"""Medusa-compatible HTTP routing for Ceto."""

from ceto.routing.response import JSON, JSONModel
from ceto.routing.router import Router

store_router = Router(prefix="/store")

__all__ = ["JSON", "JSONModel", "Router", "store_router"]
