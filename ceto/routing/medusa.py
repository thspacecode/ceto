import json

import frappe
from werkzeug.wrappers import Request, Response

from ceto.routing import ceto_router
from ceto.routing.exceptions import (
	CetoHTTPError,
	InternalServerError,
	InvalidDataError,
	MethodNotAllowedError,
	NotAllowedError,
	RouteNotFoundError,
	UnauthorizedError,
)

# Register all application endpoints after the shared routers are initialized.
import ceto.api.routes  # isort: skip


class CetoPageRenderer:
	"""Frappe website renderer that gives Ceto ownership of ``/ceto`` dispatch."""

	def __init__(self, path: str | None = None, http_status_code: int | None = None) -> None:
		self.path = (path or frappe.request.path).strip("/ ")

	def can_render(self) -> bool:
		return self.path == "ceto" or self.path.startswith("ceto/")

	def render(self) -> Response:
		frappe.flags.ceto_api_response = True
		return ceto_router.dispatch(frappe.request)


def normalize_ceto_error(response: Response, request: Request) -> None:
	"""Convert failures raised before Ceto dispatch (notably auth) to Medusa JSON."""
	path = request.path.rstrip("/")
	if (path != "/ceto" and not path.startswith("/ceto/")) or response.status_code < 400:
		return
	if getattr(frappe.flags, "ceto_api_response", False):
		return

	error = _error_for_status(response.status_code)
	response.set_data(json.dumps(error.to_dict(), separators=(",", ":")))
	response.content_type = "application/json"


def _error_for_status(status: int) -> CetoHTTPError:
	error_class = {
		400: InvalidDataError,
		401: UnauthorizedError,
		403: NotAllowedError,
		404: RouteNotFoundError,
		405: MethodNotAllowedError,
		417: NotAllowedError,
	}.get(status, InternalServerError)
	return error_class()
