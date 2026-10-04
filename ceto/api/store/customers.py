"""Thin Medusa Store Customer endpoints (Phase 2: create, retrieve, update)."""

from typing import Any

import frappe
from frappe import _

from ceto.api.store.publishable_key import CustomerPublishableKey
from ceto.routing import ceto_router
from ceto.services.auth.tokens import (
	consume_bearer_registration_token,
	get_bearer_registration_subject,
)
from ceto.services.customers.creation import create_customer_profile
from ceto.services.customers.identity import resolve_customer_reference
from ceto.services.customers.serialization import CustomerSerializer
from ceto.services.customers.update import update_customer as apply_customer_update
from ceto.types.http.store.customers import (
	StoreCreateCustomer,
	StoreGetCustomerParams,
	StoreUpdateCustomer,
)


@ceto_router.post("/store/customers", allow_guest=True)
def create_customer(fields: str | None = None, **payload: Any) -> dict[str, Any]:
	"""Medusa ``create``: complete a registration by minting the profile.

	Guest-dispatchable like every Store route because the request carries no
	customer session: it authenticates with the single-purpose
	``registration`` bearer token the register auth route issued, so an
	``auth``-purpose token never works here. The body email is the token
	subject (recorded decision 3): an omitted email falls back to it and a
	disagreeing one is refused before any write.

	The token is consumed only after the profile transaction succeeded —
	serialization included — because the used-marker lives in cache and
	survives the router's rollback: a failed create never burns the token and
	updates nothing (recorded decision 8).
	"""
	CustomerPublishableKey.from_request()
	validated = StoreCreateCustomer.model_validate(payload)
	user = get_bearer_registration_subject()
	if validated.email is not None and validated.email.lower() != user.lower():
		frappe.throw(_("Email does not match the registration token"), frappe.ValidationError)
	identity, reference = create_customer_profile(
		user,
		first_name=validated.first_name,
		last_name=validated.last_name,
		company_name=validated.company_name,
		phone=validated.phone,
		metadata=validated.metadata,
	)
	customer = CustomerSerializer.serialize(identity, reference).model_dump(mode="json")
	body = {"customer": CustomerSerializer.select_fields(customer, fields)}
	# Every failing step above rolled back; only a fully built response may
	# burn the single-use token.
	consume_bearer_registration_token()
	return body


@ceto_router.get("/store/customers/me")
def retrieve_customer(**query: Any) -> dict[str, Any]:
	"""Medusa ``retrieve``: the authenticated customer's own profile.

	Not guest-dispatchable: the router refuses every request without a
	customer session before this handler runs. A normal ``auth``-purpose
	bearer token authenticates through the shared auth hook (registration and
	password-reset tokens never authenticate), and a session user whose
	identity cannot resolve — no Contact chain, no Customer, no Ceto
	reference — is masked as the same ``401 unauthorized``.
	"""
	CustomerPublishableKey.from_request()
	params = StoreGetCustomerParams.model_validate(query)
	identity, reference = resolve_customer_reference(frappe.session.user)
	customer = CustomerSerializer.serialize(identity, reference).model_dump(mode="json")
	return {"customer": CustomerSerializer.select_fields(customer, params.fields)}


@ceto_router.post("/store/customers/me")
def update_customer(fields: str | None = None, **payload: Any) -> dict[str, Any]:
	"""Medusa ``update``: apply the body to the authenticated customer's profile.

	Not guest-dispatchable: the router refuses every request without a
	customer session before this handler runs (like ``retrieve``). A normal
	``auth``-purpose bearer token authenticates through the shared auth hook —
	``registration`` and password-reset tokens never authenticate — and a
	session user whose identity chain or ``Ceto Customer Reference`` cannot
	resolve is masked as the same ``401 unauthorized`` before any privileged
	write.

	``email`` is not part of the pinned ``StoreUpdateCustomer`` payload (the
	login identity changes through the auth verification flow), so an
	``email`` key — like every unknown field — is refused with
	``400 invalid_data`` before anything is resolved or written. The pinned
	``SelectParams`` ``fields`` selector projects the freshly serialized
	customer *after* the update ran: an invalid selector fails the request and
	the router rolls the whole update back.
	"""
	CustomerPublishableKey.from_request()
	validated = StoreUpdateCustomer.model_validate(payload)
	identity, reference = resolve_customer_reference(frappe.session.user)
	apply_customer_update(identity, reference, validated)
	customer = CustomerSerializer.serialize(identity, reference).model_dump(mode="json")
	return {"customer": CustomerSerializer.select_fields(customer, fields)}
