"""Serialize Ceto payment records onto the pinned Phase 5 payment surface.

The pinned ``StorePaymentCollection`` / ``StorePaymentSession`` shapes are
served from the persistence the 5B slice pinned (``Ceto Payment
Collection`` / ``Ceto Payment Session``), plus the projections the cart
and order serializers embed:

- ``for_cart`` / ``for_carts`` build the cart's collection — ``None``
  when the cart holds none, so a cart without payments keeps serving the
  pinned ``payment_collection: null``.
- ``payment_status`` / ``payment_statuses`` project an order's pinned
  ``payment_status`` from its cart's current session and nothing else:
  ``captured`` / ``authorized`` when the current session says so, and
  ``not_paid`` for every other state (pending, error, canceled, a stale
  or absent session) — never a fabricated ``awaiting`` or
  ``partially_*``: only proven money is reported.

Everything reads rows (``frappe.get_all``), never documents: the cart
serializer pays one indexed lookup on every cart read, and the order list
serves a whole page from the same two queries.
"""

import json

import frappe
from frappe.utils import flt, get_datetime

from ceto.types.http.store.payments import (
	StorePaymentCollection,
	StorePaymentProvider,
	StorePaymentSession,
)

COLLECTION_FIELDS = (
	"name",
	"payment_collection_id",
	"currency_code",
	"amount",
	"status",
	"creation",
	"modified",
)

SESSION_FIELDS = (
	"payment_collection",
	"payment_session_id",
	"provider_id",
	"amount",
	"currency_code",
	"provider_data",
	"status",
	"is_current",
	"creation",
	"modified",
)

#: The session states that prove money, mapped onto the pinned order
#: ``payment_status`` members. Every other session state — pending
#: attempts, errors, cancels, stale rows — means no money moved, so the
#: projection stays on the pinned ``not_paid`` default.
PROVEN_PAYMENT_STATUSES = {"captured": "captured", "authorized": "authorized"}


class PaymentSerializer:
	"""Serve the pinned payment surface from Ceto payment records."""

	@classmethod
	def for_cart(cls, cart_id: str) -> StorePaymentCollection | None:
		"""Return the cart's payment collection, or ``None`` without one."""
		return cls.for_carts([cart_id]).get(cart_id)

	@classmethod
	def for_carts(cls, cart_ids: "list[str] | set[str]") -> "dict[str, StorePaymentCollection | None]":
		"""Return the collections of many carts, two queries for the page.

		Carts without a collection map to ``None`` — the pinned
		``payment_collection`` default — and one-collection-per-cart means
		every cart key is present exactly once.
		"""
		cart_ids = {cart_id for cart_id in cart_ids if cart_id}
		serialized = {cart_id: None for cart_id in cart_ids}
		if not cart_ids:
			return serialized
		collections = {
			row.cart_reference: row
			for row in frappe.get_all(
				"Ceto Payment Collection",
				filters={"cart_reference": ("in", cart_ids)},
				fields=(*COLLECTION_FIELDS, "cart_reference"),
			)
		}
		sessions = cls._sessions_by_collection({row.name for row in collections.values()})
		for cart_id, row in collections.items():
			serialized[cart_id] = cls._build(row, sessions.get(row.name, []))
		return serialized

	@classmethod
	def payment_status(cls, cart_id: str) -> str:
		"""Return the order-facing ``payment_status`` of one cart."""
		return cls.payment_statuses([cart_id]).get(cart_id, "not_paid")

	@classmethod
	def payment_statuses(cls, cart_ids: "list[str] | set[str]") -> "dict[str, str]":
		"""Project the order-facing payment statuses of many carts.

		One query resolves the carts' collections, one their current
		sessions; the projection is the current session's proven money and
		nothing else.
		"""
		cart_ids = {cart_id for cart_id in cart_ids if cart_id}
		if not cart_ids:
			return {}
		collections = dict(
			frappe.get_all(
				"Ceto Payment Collection",
				filters={"cart_reference": ("in", cart_ids)},
				fields=["cart_reference", "name"],
				as_list=True,
			)
		)
		if not collections:
			return {cart_id: "not_paid" for cart_id in cart_ids}
		current = {
			row.payment_collection: row.status
			for row in frappe.get_all(
				"Ceto Payment Session",
				filters={"payment_collection": ("in", set(collections.values())), "is_current": 1},
				fields=["payment_collection", "status"],
			)
		}
		statuses = {}
		for cart_id in cart_ids:
			session_status = current.get(collections.get(cart_id, ""))
			statuses[cart_id] = PROVEN_PAYMENT_STATUSES.get(session_status, "not_paid")
		return statuses

	@classmethod
	def _sessions_by_collection(cls, collection_names: "set[str]") -> "dict[str, list[dict]]":
		"""Group the collections' sessions, oldest first, one query."""
		if not collection_names:
			return {}
		grouped: dict[str, list[dict]] = {}
		for row in frappe.get_all(
			"Ceto Payment Session",
			filters={"payment_collection": ("in", collection_names)},
			fields=SESSION_FIELDS,
			order_by="creation asc, name asc",
		):
			grouped.setdefault(row.payment_collection, []).append(row)
		return grouped

	@classmethod
	def _build(cls, row: "frappe._dict", sessions: "list[dict]") -> StorePaymentCollection:
		current = next((session for session in sessions if session.is_current), None)
		proven = current is not None and current.status in PROVEN_PAYMENT_STATUSES
		return StorePaymentCollection(
			id=row.payment_collection_id,
			currency_code=row.currency_code,
			amount=flt(row.amount),
			# Money columns derive from the one live session and nothing
			# else: no authorized/captured session means no proven money,
			# and the refund column stays unset until a refund flow exists.
			authorized_amount=flt(current.amount) if proven else None,
			captured_amount=flt(current.amount) if proven and current.status == "captured" else None,
			refunded_amount=None,
			completed_at=None,
			created_at=get_datetime(row.creation),
			updated_at=get_datetime(row.modified),
			status=row.status,
			payment_providers=cls._providers(sessions),
			payment_sessions=[cls._session(session) for session in sessions],
		)

	@staticmethod
	def _providers(sessions: "list[dict]") -> list[StorePaymentProvider]:
		"""The distinct providers the collection's sessions were created for."""
		return [
			StorePaymentProvider(id=provider_id)
			for provider_id in sorted({session.provider_id for session in sessions})
		]

	@staticmethod
	def _session(row: "frappe._dict") -> StorePaymentSession:
		return StorePaymentSession(
			id=row.payment_session_id,
			amount=flt(row.amount),
			currency_code=row.currency_code,
			provider_id=row.provider_id,
			data=json.loads(row.provider_data) if row.provider_data else {},
			context=None,
			status=row.status,
			authorized_at=None,
		)
