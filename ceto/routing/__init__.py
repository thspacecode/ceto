"""Medusa-compatible HTTP routing for Ceto."""

from ceto.routing.response import JSON, JSONModel
from ceto.routing.router import Router

ceto_router = Router(prefix="/ceto")

__all__ = ["JSON", "JSONModel", "Router", "ceto_router"]
