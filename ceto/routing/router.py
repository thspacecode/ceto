import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, ParamSpec, TypeVar

import frappe
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import BadRequest, HTTPException, MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

P = ParamSpec("P")
R = TypeVar("R")

_FASTAPI_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class Route:
	path: str
	method: str
	endpoint: Callable[..., Any]
	allow_guest: bool

	@property
	def key(self) -> str:
		return f"{self.method} {self.path}"

	@property
	def dotted_path(self) -> str:
		return f"{self.endpoint.__module__}.{self.endpoint.__name__}"

	@property
	def rule(self) -> str:
		return _FASTAPI_PARAMETER.sub(r"<\1>", self.path)


class InvalidRequestError(ValueError):
	"""The request payload cannot be passed to a Ceto endpoint."""


class Router:
	"""Register and directly dispatch Ceto-owned HTTP endpoints."""

	def __init__(self, *, prefix: str = "") -> None:
		self.prefix = self._normalize_prefix(prefix)
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
		"""Register a function with Ceto without exposing it through Frappe RPC."""
		method = method.upper()
		path = self._full_path(path)

		def decorator(function: Callable[P, R]) -> Callable[P, R]:
			if any(registered.path == path and registered.method == method for registered in self._routes):
				raise ValueError(f"Duplicate route: {method} {path}")

			self._routes.append(Route(path=path, method=method, endpoint=function, allow_guest=allow_guest))
			self._map = None
			return function

		return decorator

	def match(self, request: Request) -> tuple[Route, dict[str, Any]]:
		"""Resolve a request to a Ceto route and extract its path parameters."""
		route, arguments = self._url_map().bind_to_environ(request.environ).match()
		return route, arguments

	def dispatch(self, request: Request) -> Response:
		"""Dispatch a request and always return a Medusa-compatible JSON response."""
		try:
			route, path_parameters = self.match(request)
			self._check_permission(route)
			arguments = self._request_arguments(request)
			arguments.update(path_parameters)
			endpoint = self._resolve_endpoint(route)
			result = self._call_endpoint(endpoint, arguments)
			if isinstance(result, Response):
				return result
			return self._json_response(result)
		except MethodNotAllowed as exc:
			return self._error_response("method_not_allowed", "Method not allowed", exc.code)
		except NotFound as exc:
			return self._error_response("not_found", "Route not found", exc.code)
		except frappe.DoesNotExistError as exc:
			return self._error_response("not_found", str(exc) or "Resource not found", 404)
		except (InvalidRequestError, BadRequest, frappe.ValidationError, PydanticValidationError) as exc:
			return self._error_response("invalid_data", str(exc) or "Invalid request data", 400)
		except frappe.AuthenticationError:
			return self._error_response("unauthorized", "Authentication required", 401)
		except frappe.PermissionError:
			return self._error_response("not_allowed", "Not permitted", 403)
		except HTTPException as exc:
			return self._error_response("request_error", exc.description, exc.code or 500)
		except Exception:
			frappe.log_error(title="Ceto Store API request failed")
			return self._error_response("internal_error", "An unexpected error occurred", 500)

	def _url_map(self) -> Map:
		if self._map is None:
			self._map = Map(
				[Rule(route.rule, methods=[route.method], endpoint=route) for route in self._routes],
				strict_slashes=False,
				merge_slashes=False,
			)
		return self._map

	@staticmethod
	def _check_permission(route: Route) -> None:
		if not route.allow_guest and frappe.session.user in ("", "Guest"):
			raise frappe.AuthenticationError

	@staticmethod
	def _request_arguments(request: Request) -> dict[str, Any]:
		arguments = request.args.to_dict(flat=True)
		arguments.update(request.form.to_dict(flat=True))

		if request.mimetype == "application/json":
			payload = request.get_json(silent=False)
			if payload is None:
				return arguments
			if not isinstance(payload, Mapping):
				raise InvalidRequestError("JSON request body must be an object")
			arguments.update(payload)

		return arguments

	@staticmethod
	def _call_endpoint(endpoint: Callable[..., Any], arguments: dict[str, Any]) -> Any:
		signature = inspect.signature(endpoint)
		accepts_extra_arguments = any(
			parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
		)
		if not accepts_extra_arguments:
			arguments = {name: value for name, value in arguments.items() if name in signature.parameters}
		return endpoint(**arguments)

	@staticmethod
	def _resolve_endpoint(route: Route) -> Callable[..., Any]:
		overrides = frappe.get_hooks("ceto_route_overrides", {}).get(route.key, [])
		if not overrides:
			return route.endpoint
		return frappe.get_attr(overrides[-1])

	@staticmethod
	def _json_response(payload: Any, status: int = 200) -> Response:
		return Response(
			json.dumps(payload, separators=(",", ":"), default=str),
			status=status,
			content_type="application/json",
		)

	@classmethod
	def _error_response(cls, error_type: str, message: str, status: int) -> Response:
		return cls._json_response({"type": error_type, "message": message}, status=status)

	def _full_path(self, path: str) -> str:
		path = self._normalize_path(path)
		if not self.prefix:
			return path
		if path == "/":
			return self.prefix
		return f"{self.prefix}{path}"

	@staticmethod
	def _normalize_prefix(prefix: str) -> str:
		if not prefix:
			return ""
		prefix = Router._normalize_path(prefix)
		return prefix.rstrip("/")

	@staticmethod
	def _normalize_path(path: str) -> str:
		if not path.startswith("/"):
			raise ValueError("Route paths must start with '/'")
		return path
