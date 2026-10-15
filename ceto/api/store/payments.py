"""Store payment HTTP surface: the thin adapter over ``PaymentSessions``.

Phase 5 slices 5C/5D register the pinned three-route payment surface of
``@medusajs/medusa@2.21.1`` (see ``ceto/types/http/store/payments/
manifest.py``): the provider list, the collection create (the SDK's
``initiatePaymentSession`` inlines it before a first session) and the
session creation. All three are guest-dispatchable with no customer
authentication — checkout is guest-first — and every one requires the
``x-publishable-api-key`` header, validated exactly like the cart routes:
the key must exist, and a scoped key may only operate inside its region.

Foreign and unknown resources never answer: an unknown or
wrong-scoped/owned cart (and the collection id sitting on it) masks as
``404 not_found``; an unknown or disabled provider is a stable
``400 invalid_data``; a provider backend that is absent or failing is a
stable ``200`` carrying a ``pending`` session with no provider data.
"""

from typing import Any

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.payments.providers import default_registry
from ceto.services.payments.serialization import PaymentSerializer
from ceto.services.payments.sessions import PaymentSessions
from ceto.services.serialization import select_fields
from ceto.types.http.store.payments import (
	StoreCreatePaymentCollection,
	StoreGetPaymentProvidersParams,
	StoreInitializePaymentSession,
	StorePaymentProvider,
	StorePaymentProviderListResponse,
)


@ceto_router.get("/store/payment-providers", allow_guest=True)
def list_payment_providers(**query: Any) -> dict[str, Any]:
	"""Medusa ``listPaymentProviders``: page the enabled payment providers.

	The pinned query is strict: ``region_id`` is required (the route
	refuses without it), ``limit`` / ``offset`` carry the upstream defaults
	(20 / 0) and every other key is rejected. The enabled answers come
	from the Ceto provider registry — a site without an enabled gateway
	serves an empty page, never an error. The response is the pinned
	``PaginatedResponse`` envelope.
	"""
	publishable_key = CartPublishableKey.from_request()
	params = StoreGetPaymentProvidersParams.model_validate(query)
	publishable_key.check_values(params.region_id, None)
	providers = default_registry().enabled()
	page = providers[params.offset : params.offset + params.limit]
	response = StorePaymentProviderListResponse(
		payment_providers=[StorePaymentProvider(id=provider.id) for provider in page],
		count=len(providers),
		offset=params.offset,
		limit=params.limit,
	)
	return response.model_dump(mode="json")


@ceto_router.post("/store/payment-collections", allow_guest=True)
def create_payment_collection(fields: str | None = None, **payload: Any) -> dict[str, Any]:
	"""Medusa collection create: return the cart's (upserted) collection.

	The strict body carries the cart id; amount and currency are derived
	server-side from the cart's current payable. The scope check runs
	inside the cart row lock (before any write), so a wrong-scoped key can
	neither create the collection nor distinguish a foreign cart from a
	missing one.
	"""
	publishable_key = CartPublishableKey.from_request()
	validated = StoreCreatePaymentCollection.model_validate(payload)
	collection = PaymentSessions().create_collection(validated.cart_id, guard=publishable_key.check_reference)
	return {"payment_collection": _selected(collection, fields)}


@ceto_router.post("/store/payment-collections/{id}/payment-sessions", allow_guest=True)
def create_payment_session(id: str, fields: str | None = None, **payload: Any) -> dict[str, Any]:
	"""Medusa ``initiatePaymentSession``: book and charge the cart's session.

	The strict body names the ``pp_…`` provider (plus its optional
	``data``). Session creation is idempotent on provider + cart + current
	payable; the charge goes through the narrow paygi boundary and its
	response becomes the session's ``data``. The whole collection — with
	its sessions and provider identity — is the pinned answer.
	"""
	publishable_key = CartPublishableKey.from_request()
	validated = StoreInitializePaymentSession.model_validate(payload)
	collection = PaymentSessions().initialize_session(id, validated, guard=publishable_key.check_reference)
	return {"payment_collection": _selected(collection, fields)}


def _selected(collection, fields: str | None) -> dict[str, Any]:
	"""Serialize one collection and apply the shared ``fields`` selector."""
	return select_fields(collection.model_dump(mode="json"), fields, entity="payment_collection")
