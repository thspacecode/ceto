"""Entity-neutral serialization helpers shared by the store services.

The pinned ``fields`` query parameter behaves identically on every store
route and entity (carts and orders alike): a comma-separated token list
over the top-level fields of one serialized entity, with ``+``/``-`` tokens
adding to or removing from the full selection and dotted paths truncated to
their top-level field. The selector lives here so neither the cart nor the
order surface needs the other's serializer for field selection.
"""

from typing import Any

from ceto.routing.exceptions import InvalidDataError


def select_fields(payload: dict[str, Any], fields: str | None, *, entity: str) -> dict[str, Any]:
	"""Apply the shared ``fields`` selector to one serialized entity.

	Plain tokens narrow the payload to exactly those fields; on a token
	list of only ``+``/``-`` tokens the selection starts from the full
	payload. Unknown fields fail closed with ``400 invalid_data`` instead
	of being ignored — a client must never receive a page it cannot
	reproduce. ``entity`` only names the field in the error messages (the
	completion response is a union, so the same selector serves both
	members).
	"""
	if not fields:
		return payload

	tokens = [token.strip() for token in fields.split(",") if token.strip()]
	plain_fields = {_field_name(token, entity) for token in tokens if token[0] not in "+-*"}
	selected = plain_fields or set(payload)
	for token in tokens:
		field = _field_name(token, entity)
		if field not in payload:
			raise InvalidDataError(f"Unknown {entity} field: {field}")
		if token.startswith("-"):
			selected.discard(field)
		else:
			selected.add(field)
	return {key: value for key, value in payload.items() if key in selected}


def _field_name(token: str, entity: str) -> str:
	"""Return a token's top-level field; an empty one is invalid input."""
	field = token.lstrip("+-*").split(".", 1)[0]
	if not field:
		raise InvalidDataError(f"{entity.capitalize()} fields must not be empty")
	return field
