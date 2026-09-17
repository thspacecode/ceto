import json

import frappe
from werkzeug.exceptions import NotFound
from werkzeug.wrappers import Request, Response

from ceto.routing import router

# Import endpoint modules so their decorators populate the route registry.
import ceto.api.auth.customer  # noqa: E402, F401


def route_request() -> None:
	"""Translate a Medusa path into a normal Frappe whitelisted-method call."""
	try:
		endpoint, path_parameters = router.match(frappe.request)
	except NotFound:
		return

	frappe.form_dict.cmd = endpoint
	frappe.form_dict.update(path_parameters)
	frappe.flags.ceto_medusa_request = True


def normalize_response(response: Response, request: Request) -> None:
	"""Remove Frappe's RPC envelope from successful Medusa-route responses."""
	if not getattr(frappe.flags, "ceto_medusa_request", False) or not response.is_json:
		return

	payload = response.get_json(silent=True)
	if not 200 <= response.status_code < 300 or not isinstance(payload, dict) or "message" not in payload:
		return

	response.set_data(json.dumps(payload["message"], separators=(",", ":"), default=str))
	response.content_type = "application/json"
