import json

import frappe
from werkzeug.wrappers import Request, Response

from ceto.routing import store_router


class CetoPageRenderer:
	"""Frappe website renderer that gives Ceto ownership of ``/store`` dispatch."""

	def __init__(self, path: str | None = None, http_status_code: int | None = None) -> None:
		self.path = (path or frappe.request.path).strip("/ ")

	def can_render(self) -> bool:
		return self.path == "store" or self.path.startswith("store/")

	def render(self) -> Response:
		frappe.flags.ceto_store_response = True
		return store_router.dispatch(frappe.request)


def normalize_store_error(response: Response, request: Request) -> None:
	"""Convert failures raised before Ceto dispatch (notably auth) to Medusa JSON."""
	path = request.path.rstrip("/")
	if (path != "/store" and not path.startswith("/store/")) or response.status_code < 400:
		return
	if getattr(frappe.flags, "ceto_store_response", False):
		return

	error_type, message = _error_for_status(response.status_code)
	response.set_data(json.dumps({"type": error_type, "message": message}, separators=(",", ":")))
	response.content_type = "application/json"


def _error_for_status(status: int) -> tuple[str, str]:
	if status == 400:
		return "invalid_data", "Invalid request data"
	if status == 401:
		return "unauthorized", "Authentication required"
	if status == 403:
		return "not_allowed", "Not permitted"
	if status == 404:
		return "not_found", "Route not found"
	if status == 405:
		return "method_not_allowed", "Method not allowed"
	return "internal_error", "An unexpected error occurred"
