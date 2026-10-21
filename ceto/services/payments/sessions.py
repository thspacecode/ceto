"""Store payment collection/session orchestration (Phase 5 slices 5C/5D).

The routes in ``ceto.api.store.payments`` are thin adapters over this
service. It owns the two checkout flows the pinned Medusa surface serves:

- **Collection creation** (``POST /store/payment-collections``): one
  collection per cart, amount and currency derived server-side from the
  cart's current payable — the request carries the cart id and nothing
  else. An existing collection is returned as-is (Medusa's upsert
  semantics, enforced by the unique cart link).
- **Session creation** (``POST /store/payment-collections/{id}/
  payment-sessions``): resolves the collection's cart, books the
  idempotent current session (5B semantics), then charges through the
  narrow paygi boundary (:mod:`ceto.services.payments.gateway`). The
  provider's response — payment ids, status, the storefront action and
  ``checkout_url`` — becomes the session's ``data`` payload; a provider
  that is absent or failing leaves a stable ``pending`` session with no
  data instead of an accidental 500.

Both flows run inside the cart row lock with the route's publishable-key
scope check as ``guard`` — the same lock-and-guard discipline every cart
mutation uses — so a wrong-scoped key can neither create payment state
nor learn that a foreign cart exists (everything foreign masks as
``404 not_found``). The flows also row-lock the collection before any
session write (``PaymentCollections.lock_collection``), the order the
paygi success webhook uses, so a capture racing a recreation serializes
instead of deadlocking.
"""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import frappe
from frappe.utils import flt

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.access import CartAccess
from ceto.services.payments import gateway as payment_gateway
from ceto.services.payments import synchronization
from ceto.services.payments.collections import PaymentCollections
from ceto.services.payments.gateway import ProviderChargeRequest, gateway_for
from ceto.services.payments.providers import ProviderRegistry
from ceto.services.payments.serialization import PaymentSerializer
from ceto.types.http.store.payments import StoreInitializePaymentSession, StorePaymentCollection

if TYPE_CHECKING:
	from frappe.model.document import Document


class PaymentSessions:
	"""Create carts' payment collections and their provider sessions."""

	def __init__(
		self,
		access: CartAccess | None = None,
		registry: ProviderRegistry | None = None,
		create_payment: "Callable[[ProviderChargeRequest], dict[str, Any] | None] | None" = None,
	) -> None:
		self.access = access or CartAccess()
		self.registry = registry
		self.create_payment = create_payment or payment_gateway.create_payment

	def create_collection(
		self,
		cart_id: str,
		*,
		guard: Callable | None = None,
	) -> StorePaymentCollection:
		"""Return the cart's collection, creating it when missing."""
		with self.access.lock(cart_id) as (reference, _quotation):
			if guard is not None:
				guard(reference)
			PaymentCollections.ensure_collection(reference.cart_id)
			return self._serialize(reference.cart_id)

	def initialize_session(
		self,
		collection_id: str,
		payload: StoreInitializePaymentSession,
		*,
		guard: Callable | None = None,
	) -> StorePaymentCollection:
		"""Book the collection's current session and charge it, idempotently.

		The collection id is resolved first and everything foreign — an
		unknown collection, an unknown or claimed cart behind it — masks as
		``404 not_found`` through the cart access layer.
		"""
		cart_id = self._collection_cart(collection_id)
		with self.access.lock(cart_id) as (reference, _quotation):
			if guard is not None:
				guard(reference)
			session = PaymentCollections.ensure_session(
				reference.cart_id, payload.provider_id, registry=self.registry
			)
			self._charge(session, payload.data)
			return self._serialize(reference.cart_id)

	@staticmethod
	def _collection_cart(collection_id: str) -> str:
		"""Return the cart a collection collects for; unknown ids mask as 404."""
		cart_id = frappe.db.get_value(
			"Ceto Payment Collection", {"payment_collection_id": collection_id}, "cart_reference"
		)
		if not cart_id:
			raise RouteNotFoundError("Payment collection not found")
		return cart_id

	def _charge(self, session: "Document", data: "dict[str, Any] | None") -> None:
		"""Charge the session through the provider, or leave it pending.

		The wrapper's ``None`` — provider absent, unreachable or failing —
		is a stable outcome: the session stays ``pending`` with empty
		provider data and the creation answer carries it, so the client can
		retry (a retry books a fresh attempt, never a duplicate charge).
		An injected boundary that raises is absorbed the same way: a
		payment route must never turn a provider fault into a 500.
		"""
		try:
			response = self.create_payment(
				ProviderChargeRequest(
					session_id=session.payment_session_id,
					gateway=gateway_for(session.provider_id),
					amount=flt(session.amount),
					currency_code=session.currency_code,
					data=data,
				)
			)
		except Exception:
			frappe.log_error(
				title="Ceto payment provider charge failed",
				message=f"{session.provider_id} session {session.payment_session_id}: provider unavailable",
			)
			return
		if response is None:
			return
		self._apply_response(session, response)

	@staticmethod
	def _apply_response(session: "Document", response: "dict[str, Any]") -> None:
		"""Persist the provider payload and project terminal attempt states.

		Only a terminal attempt status moves the session off ``pending``: a
		succeeded attempt captures the session exactly once (and completes
		the collection with it), a failed one marks the session ``error``
		so the next creation books a fresh attempt, a canceled one marks it
		``canceled``. In-flight states keep the session pending.
		"""
		frappe.db.set_value(
			"Ceto Payment Session", session.name, "provider_data", json.dumps(response, default=str)
		)
		terminal = synchronization.attempt_status_to_session(response.get("status"))
		if terminal == synchronization.SESSION_CAPTURED:
			synchronization.capture_session(session.payment_session_id)
		elif terminal is not None:
			frappe.db.set_value("Ceto Payment Session", session.name, "status", terminal)

	def _serialize(self, cart_id: str) -> StorePaymentCollection:
		"""Serialize the cart's collection from its committed rows."""
		serialized = PaymentSerializer.for_cart(cart_id)
		if serialized is None:
			# The collection was ensured above; a miss here is a broken
			# invariant, not a client error.
			raise RouteNotFoundError("Payment collection not found")
		return serialized
