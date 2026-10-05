"""Store order HTTP surface: the thin adapter over ``OrderService``.

Phase 2 wires the pinned retrieve route, Phase 3 the list route, Phase 4
the transfer ``request``/``cancel`` routes and Phase 5 the transfer
``accept``/``decline`` routes — the full pinned six-route surface.
"""

from typing import Any

import frappe

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.carts.customers import CartCustomers
from ceto.services.orders.service import OrderService
from ceto.types.http.store.orders import (
	StoreAcceptOrderTransfer,
	StoreDeclineOrderTransfer,
	StoreOrderFilters,
	StoreRequestOrderTransfer,
)

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


@ceto_router.post("/store/orders/{id}/transfer/request")
def request_order_transfer(id: str, **payload: Any) -> dict[str, Any]:
	"""Medusa ``requestTransfer``: ask ownership of a guest order for the caller.

	Customer-authenticated like upstream pins it: the router refuses an
	anonymous session before the handler and ``CartCustomers`` refuses a
	customer-less one — both ``401 unauthorized`` — with the publishable
	key required exactly as on every Store route. The body validates
	against the pinned ``StoreRequestOrderTransfer``, whose unknown fields
	are forbidden: upstream pins no recipient identifier, so the requester
	is always the authenticated customer and the requester email is derived
	from the session's User → Contact convention (see
	``_session_requester_email``), never read from the payload (orders
	Recorded Decision 9). Resolution and eligibility live in the service —
	unknown, broken, cancelled and wrong-scoped orders are the masked
	``404 not_found`` of retrieve, an owned order or a second live request
	is ``400 invalid_data`` — and the single-use token reaches only the
	``ceto_order_transfer_requested`` hook.

	The response is the exact pinned ``StoreOrderResponse`` — the unchanged
	``{order}`` — with no ``fields`` selector and never a token.
	"""
	publishable_key = CartPublishableKey.from_request()
	customer = CartCustomers.resolve(frappe.session.user)
	validated = StoreRequestOrderTransfer.model_validate(payload)
	order = OrderService().request_transfer(
		id,
		publishable_key,
		requested_by=customer,
		requester_email=_session_requester_email(frappe.session.user),
		description=validated.description,
		update_order_email=validated.update_order_email,
	)
	return {"order": order}


@ceto_router.post("/store/orders/{id}/transfer/cancel")
def cancel_order_transfer(id: str) -> dict[str, Any]:
	"""Medusa ``cancelTransfer``: remove the caller's pending transfer request.

	Customer-authenticated exactly like the request route — publishable
	key, then the session's Customer, both ``401 unauthorized`` when
	missing — and bodyless (the pinned manifest carries
	``request_type: None``): the handler takes no body parameter, so a sent
	body is never read. Only the recorded requester's pending record is
	removed (any other caller ``403 not_allowed``, a missing or replayed
	request ``400 invalid_data``).

	The response is the exact pinned ``StoreOrderResponse`` — the unchanged
	``{order}`` — with no ``fields`` selector and never a token.
	"""
	publishable_key = CartPublishableKey.from_request()
	customer = CartCustomers.resolve(frappe.session.user)
	order = OrderService().cancel_transfer(id, publishable_key, requested_by=customer)
	return {"order": order}


@ceto_router.post("/store/orders/{id}/transfer/accept", allow_guest=True)
def accept_order_transfer(id: str, **payload: Any) -> dict[str, Any]:
	"""Medusa ``acceptTransfer``: consent to a pending transfer with its token.

	Token-authorized like upstream pins it: the accept route carries no
	customer authentication middleware upstream — the single-use transfer
	token in the body authorizes — so the handler is guest-dispatchable and
	never resolves a session Customer. The publishable key is still
	required exactly as on every Store route, and the body validates
	against the pinned ``StoreAcceptOrderTransfer`` whose unknown fields
	are forbidden. Everything else lives in the service: the presented
	token is only ever hashed, every failing credential — wrong, expired,
	replayed consumed or declined — is the same ``403 not_allowed``
	``Invalid token.`` without mutation, a digest matching no record of an
	order without a live pending request is ``400 invalid_data``, and
	resolution is the masked ``404 not_found`` of retrieve.

	The response is the exact pinned ``StoreOrderResponse`` — the updated
	``{order}`` — with no ``fields`` selector and never a token.
	"""
	publishable_key = CartPublishableKey.from_request()
	validated = StoreAcceptOrderTransfer.model_validate(payload)
	order = OrderService().accept_transfer(id, publishable_key, token=validated.token)
	return {"order": order}


@ceto_router.post("/store/orders/{id}/transfer/decline", allow_guest=True)
def decline_order_transfer(id: str, **payload: Any) -> dict[str, Any]:
	"""Medusa ``declineTransfer``: refuse a pending transfer with its token.

	Token-authorized exactly like the accept route — no customer
	authentication middleware, the body's single-use transfer token
	authorizes, the publishable key is required exactly as on every Store
	route and the body validates against the pinned
	``StoreDeclineOrderTransfer`` whose unknown fields are forbidden. The
	same lock, masked resolution and credential gates as acceptance apply;
	the holder's refusal closes the pending record ``Declined`` and writes
	nothing else (orders Recorded Decision 12).

	The response is the exact pinned ``StoreOrderResponse`` — the unchanged
	``{order}`` — with no ``fields`` selector and never a token.
	"""
	publishable_key = CartPublishableKey.from_request()
	validated = StoreDeclineOrderTransfer.model_validate(payload)
	order = OrderService().decline_transfer(id, publishable_key, token=validated.token)
	return {"order": order}


def _session_requester_email(user: str) -> str | None:
	"""The caller's email per the authenticated User → Contact convention.

	The chain that resolves the session's Customer (``CartCustomers``)
	also carries the customer-facing email: the linked Contact's
	``email_id``, with the User's own login email as the fallback. The
	transfer's ``update_order_email`` target is therefore always derived
	from the authenticated session — the pinned request body carries no
	recipient identifier and must never gain one through the back door.
	"""
	contact_email = frappe.db.get_value("Contact", {"user": user}, "email_id", order_by="creation asc")
	return contact_email or frappe.db.get_value("User", user, "email")


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
