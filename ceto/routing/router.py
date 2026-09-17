import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

import frappe
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request

P = ParamSpec("P")
R = TypeVar("R")

_FASTAPI_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class Route:
	path: str
	method: str
	endpoint: str


class Router:
	"""Register Medusa paths while retaining Frappe's whitelisted method dispatch."""

	def __init__(self) -> None:
		self._routes: list[Route] = []
		self._map: Map | None = None

	def get(self, path: str, *, allow_guest: bool = False):
		return self.route(path, method="GET", allow_guest=allow_guest)

	def post(self, path: str, *, allow_guest: bool = False):
		return self.route(path, method="POST", allow_guest=allow_guest)

	def put(self, path: str, *, allow_guest: bool = False):
		return self.route(path, method="PUT", allow_guest=allow_guest)

	def delete(self, path: str, *, allow_guest: bool = False):
		return self.route(path, method="DELETE", allow_guest=allow_guest)

	def route(self, path: str, *, method: str, allow_guest: bool = False):
		"""Register a public route and whitelist the decorated Frappe method."""
		method = method.upper()
		path = self._normalize_path(path)

		def decorator(function: Callable[P, R]) -> Callable[P, R]:
			whitelisted = frappe.whitelist(allow_guest=allow_guest, methods=[method])(function)
			endpoint = f"{whitelisted.__module__}.{whitelisted.__name__}"
			route = Route(path=path, method=method, endpoint=endpoint)
			if any(registered.path == path and registered.method == method for registered in self._routes):
				raise ValueError(f"Duplicate route: {method} {path}")
			self._routes.append(route)
			self._map = None
			return whitelisted

		return decorator

	def match(self, request: Request) -> tuple[str, dict[str, Any]]:
		"""Resolve a request to a whitelisted method and extracted path parameters."""
		endpoint, arguments = self._url_map().bind_to_environ(request.environ).match()
		return endpoint, arguments

	def _url_map(self) -> Map:
		if self._map is None:
			self._map = Map(
				[
					Rule(route.path, methods=[route.method], endpoint=route.endpoint)
					for route in self._routes
				],
				strict_slashes=False,
				merge_slashes=False,
			)
		return self._map

	@staticmethod
	def _normalize_path(path: str) -> str:
		if not path.startswith("/"):
			raise ValueError("Route paths must start with '/'")
		# Accept FastAPI-style path parameters while using Werkzeug internally.
		return _FASTAPI_PARAMETER.sub(r"<\1>", path)
