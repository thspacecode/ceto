"""Store order HTTP surface: the thin adapter over ``OrderService``.

Phase 2 wires the pinned retrieve route and Phase 3 the list route; the
boundary tests prove the four transfer routes stay contract-only until
their phase registers them.
"""

from typing import Any

import frappe

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.carts.customers import CartCustomers
from ceto.services.orders.service import OrderService
from ceto.types.http.store.orders import StoreOrderFilters

#: The filters whose pinned wire format is a single value or an array: the
#: SDK serializes a list as one comma-separated value (or repeated
#: parameters), while the router flattens repeated query keys to the last.
FILTER_PARAMS = ("id", "status")


@ceto_router.get("/store/orders/{id}", allow_guest=True)
def retrieve_order(id: str, fields: str | None = None) -> dict[str, Any]:
	"""Medusa ``retrieve``: serve the placed order of a public ``order_…`` id.

	Guest-dispatchable like upstream pins it — the unguessable id is the
	capability (orders Recorded Decision 4) — but never anonymous: the
	publishable key is resolved and required exactly as on every Store
	route. An unknown id, broken lineage and a wrong-scoped key are all the
	same masked ``404 not_found`` from the service (Recorded Decision 5).
	"""
	publishable_key = CartPublishableKey.from_request()
	order = OrderService().retrieve(id, publishable_key, fields=fields)
	return {"order": order}


@ceto_router.get("/store/orders")
def list_orders(**query: Any) -> dict[str, Any]:
	"""Medusa ``list``: page the authenticated customer's placed orders.

	Customer-authenticated like upstream pins it — the router refuses an
	anonymous session, and the session user resolves to its Customer through
	the same ``CartCustomers`` chain the cart claim uses, so the page is
	always scoped to the caller's own customer id, never a client-supplied
	filter (orders Recorded Decisions 2 and 4). The publishable key is
	resolved and required as on every Store route; its scope filters the
	page instead of masking (a read-only list refuses nothing).

	The query validates against the pinned ``StoreOrderFilters`` — unknown
	keys, the ``$and``/``$or`` combinators, ``order`` sort expressions and
	``with_deleted`` fail as ``400 invalid_data`` instead of being ignored
	(Recorded Decision 8) — and the response is the exact pinned
	``{orders, count, offset, limit}`` envelope.
	"""
	publishable_key = CartPublishableKey.from_request()
	customer = CartCustomers.resolve(frappe.session.user)
	filters = StoreOrderFilters.model_validate(_filter_values(query))
	return OrderService().list(
		customer,
		publishable_key,
		ids=filters.id,
		statuses=filters.status,
		limit=filters.limit,
		offset=filters.offset,
		fields=filters.fields,
	)


def _filter_values(query: dict[str, Any]) -> dict[str, Any]:
	"""Replace the router-flattened filter params with their parsed values.

	The router flattens repeated query parameters to the last value; the
	pinned array wire format — one comma-separated value or repeated
	parameters, the SDK's ``qs`` serializations — is read back from the raw
	multi-value arguments, so ``?id=a,b`` and ``?id=a&id=b`` both validate as
	the list the client asked for. Every other key rides untouched into the
	strict model, which rejects it as unknown.
	"""
	arguments = dict(query)
	if frappe.request is not None:
		for name in FILTER_PARAMS:
			values = frappe.request.args.getlist(name)
			if values:
				parts = [part for value in values for part in value.split(",")]
				arguments[name] = parts[0] if len(parts) == 1 else parts
	return arguments
