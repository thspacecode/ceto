"""Cart completion (Medusa ``POST /store/carts/{id}/complete`` service).

Completion turns a cart into a placed order inside one locked, atomic
transaction. The Store route is ``ceto.api.store.carts.complete_cart``;
this module owns the whole flow the route serves.

Flow (:meth:`CartCompletion.complete`):

- The cart is row-locked first (``CartAccess.lock_for_completion``), so a
  completion serializes against concurrent cart mutations; a cart owned by
  another authenticated user is masked as ``404 not_found``.
- **Replay**: an existing ``Ceto Order Reference`` for the cart id is
  resolved and its order re-serialized instead of placing a second order.
  One cart completes once — the reference's unique indexes enforce it, and
  because the submitted Quotation takes the cart off every cart route, the
  replay lookup by ``cart_id`` is the only way back to the order.
- **Preflight** (draft carts only) produces a structured refusal union
  instead of raising: required cart state (items, email, shipping address,
  applied shipping method), an optional stock check and the payment
  readiness gate. A refusal returns the pinned ``type: "cart"`` response
  member (the untouched cart plus the ``error`` object); the cart stays
  open and the client may fix and retry.

  * Payment readiness is **open by default**: with no provider hook
    registered, completion proceeds without a payment gate (Recorded
    Decision 7). A registered hook's first falsy verdict fails the
    completion closed, before any money moves or any order is created.
  * The stock check is **off by default** (``ceto_cart_stock_check``
    site-config); when enabled, every stocked item row must have ERPNext
    projected stock in its warehouse covering the cart quantity.
- **Settle** (no refusal): the Quotation's validity is refreshed (Medusa
  carts never expire; the ERPNext quotation-validity artifact must not
  block an old cart), the Quotation is submitted, mapped into a submitted
  Sales Order through ERPNext's own mapper with the stored pricing
  preserved (``ceto.services.carts.conversion``), every Sales Order row is
  asserted back onto a cart line mapping of this cart, the ``Ceto Order
  Reference`` is booked and the wallets behind the cart's credit holds are
  consumed — all inside the ``ceto_cart_completion_settle`` savepoint, so
  an expected validation failure rolls back to the savepoint and returns
  the pinned ``OrderPlacementError`` refusal for the untouched open cart.

The pinned response is the discriminated union of ``@medusajs/types``
2.21.1: ``type: "order"`` carries the placed order, ``type: "cart"`` the
open cart plus the structured ``error`` object.
"""

import secrets
from collections.abc import Callable
from dataclasses import dataclass

import frappe
from frappe.utils import cint, flt, getdate, today

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.carts.access import CartAccess
from ceto.services.carts.conversion import convert_quotation_to_sales_order
from ceto.services.carts.credits import CartCredits
from ceto.services.carts.serialization import CartSerializer
from ceto.services.carts.shipping import CartShipping
from ceto.services.common import privileged_scope
from ceto.services.orders.serialization import OrderSerializer
from ceto.types.http.store.carts import (
	StoreCart,
	StoreCompleteCart,
	StoreCompleteCartError,
)
from ceto.types.http.store.carts.responses import (
	StoreCompleteCartFailure,
	StoreCompleteCartResponse,
	StoreCompleteCartSuccess,
)
from ceto.types.http.store.orders import StoreOrder

#: Optional fail-closed payment gate (Recorded Decision 7): registered
#: methods receive ``cart_id``, ``quotation`` and ``idempotency_key`` and
#: return a verdict; no hook — open, the first falsy (non-``None``) verdict
#: refuses the completion. Hooks run synchronously inside the cart row lock,
#: so a registered method must be local and bounded — a provider that must
#: reach a gateway records its intent locally and decides asynchronously.
PAYMENT_READINESS_HOOK = "ceto_cart_payment_readiness"

#: Site-config switch for the optional pre-completion stock check (off by
#: default): ``bench set-config ceto_cart_stock_check 1``.
STOCK_CHECK_CONFIG = "ceto_cart_stock_check"

#: Name of the settle's savepoint: a failed placement is undone with
#: ``ROLLBACK TO SAVEPOINT`` — the Quotation submission, the Sales Order,
#: the order reference and the wallet debits — without releasing the cart
#: row lock or ending the request transaction.
SETTLE_SAVEPOINT = "ceto_cart_completion_settle"

#: Expected settle failures — the Frappe/ERPNext business-validation family
#: the placement can hit, mapped onto the pinned ``OrderPlacementError``
#: refusal. Anything wider (``CetoHTTPError``, authentication/permission,
#: pydantic and database faults) is a programming or infrastructure error
#: and keeps surfacing as ``500 internal_error`` with the full request
#: rollback, never masquerading as a client-fixable cart refusal.
SETTLE_EXPECTED_EXCEPTIONS = (frappe.ValidationError,)


def new_order_id() -> str:
	"""Return a stable public order id: ``order_`` + 128 bits of crypto random."""
	return f"order_{secrets.token_hex(16)}"


@dataclass(frozen=True)
class CompletionRefusal:
	"""One preflight refusal, mapped onto the pinned ``error`` object.

	``name`` and ``type`` are the machine-readable identity Medusa clients
	switch on (``PaymentReadinessError`` / ``payment_error``), ``message``
	the human-readable text echoed back with the open cart.
	"""

	name: str
	type: str
	message: str


PAYMENT_NOT_READY = CompletionRefusal(
	name="PaymentReadinessError",
	type="payment_error",
	message="Payment is not ready for this cart",
)
EMPTY_CART = CompletionRefusal(
	name="EmptyCartError",
	type="incomplete_cart",
	message="Cart is empty",
)
MISSING_EMAIL = CompletionRefusal(
	name="MissingCartEmailError",
	type="incomplete_cart",
	message="Cart is missing an email",
)
MISSING_SHIPPING_ADDRESS = CompletionRefusal(
	name="MissingShippingAddressError",
	type="incomplete_cart",
	message="Cart is missing a shipping address",
)
MISSING_SHIPPING_METHOD = CompletionRefusal(
	name="MissingShippingMethodError",
	type="incomplete_cart",
	message="Cart is missing a shipping method",
)
INSUFFICIENT_STOCK = CompletionRefusal(
	name="InsufficientStockError",
	type="insufficient_stock",
	message="Cart items are out of stock",
)
ORDER_PLACEMENT_FAILED = CompletionRefusal(
	name="OrderPlacementError",
	type="order_placement_error",
	message="The order could not be placed; the cart was left open",
)


class CartCompletion:
	"""Complete a locked cart into an order, or refuse it with its cart."""

	def __init__(
		self,
		access: CartAccess | None = None,
		serializer: CartSerializer | None = None,
		orders: OrderSerializer | None = None,
	) -> None:
		self.access = access or CartAccess()
		self.serializer = serializer or CartSerializer()
		self.orders = orders or OrderSerializer()

	def complete(
		self,
		cart_id: str,
		payload: StoreCompleteCart | None = None,
		*,
		guard: Callable | None = None,
	) -> StoreCompleteCartResponse:
		"""Complete ``cart_id``; returns the pinned completion response union.

		``payload`` is the pinned (empty-by-default) completion body; its
		optional ``idempotency_key`` is forwarded to the payment readiness
		hooks. ``guard`` runs against the row-locked reference before
		anything else, matching the lock order of the cart mutations (the
		later route passes the publishable-key scope check).
		"""
		payload = payload or StoreCompleteCart()
		with self.access.lock_for_completion(cart_id) as (reference, quotation):
			if guard is not None:
				guard(reference)
			replayed = self._replay(reference)
			if replayed is not None:
				return replayed
			if quotation.docstatus != 0:
				# A submitted Quotation without its order reference cannot
				# happen through this flow (the settle is one transaction);
				# anything reaching here is masked like a broken cart.
				raise RouteNotFoundError("Cart not found")
			refusal = self._preflight(reference, quotation, payload)
			if refusal is not None:
				return self._failure(reference, quotation, refusal)
			return self._settle(reference, quotation, payload)

	def _replay(self, reference) -> StoreCompleteCartSuccess | None:
		"""Return the order a previous completion placed for this cart.

		The completed cart's Quotation has left the draft state every cart
		route requires, so the order reference — resolved by the unique
		``cart_id`` — is the only way back; the same order is re-serialized
		instead of mapping a second Sales Order.
		"""
		name = frappe.db.get_value("Ceto Order Reference", {"cart_id": reference.cart_id}, "name")
		if not name:
			return None
		order_reference = frappe.get_doc("Ceto Order Reference", name)
		sales_order = frappe.get_doc("Sales Order", order_reference.sales_order)
		order = StoreOrder.model_validate(self.orders.serialize(order_reference, sales_order, reference))
		return StoreCompleteCartSuccess(order=order)

	def _preflight(self, reference, quotation, payload: StoreCompleteCart) -> CompletionRefusal | None:
		"""Return the first refusal, in the pinned order, or ``None``.

		Required cart state first (items, email, shipping address, shipping
		method), then the optional stock check, then the payment readiness
		gate — the gate is evaluated last so a provider is never asked to
		authorize a cart that cannot be placed anyway.
		"""
		if not quotation.items:
			return EMPTY_CART
		if not quotation.contact_email:
			return MISSING_EMAIL
		if not quotation.shipping_address_name:
			return MISSING_SHIPPING_ADDRESS
		if CartShipping.applied_charge(quotation) is None:
			return MISSING_SHIPPING_METHOD
		if self._stock_check_enabled():
			shortages = self._stock_shortages(quotation)
			if shortages:
				return CompletionRefusal(
					name=INSUFFICIENT_STOCK.name,
					type=INSUFFICIENT_STOCK.type,
					message=f"{INSUFFICIENT_STOCK.message}: {', '.join(shortages)}",
				)
		return self._payment_refusal(reference, quotation, payload)

	def _payment_refusal(self, reference, quotation, payload: StoreCompleteCart) -> CompletionRefusal | None:
		"""Consult the registered payment readiness hooks (default open).

		Hook paths come exclusively from installed-app hooks configuration,
		not request input. A ``None`` verdict means "no opinion" and keeps
		the gate open; the first falsy verdict fails the completion closed.
		"""
		for method in frappe.get_hooks(PAYMENT_READINESS_HOOK, []):
			verdict = frappe.call(  # nosemgrep
				frappe.get_attr(method),
				cart_id=reference.cart_id,
				quotation=quotation.name,
				idempotency_key=payload.idempotency_key,
			)
			if verdict is not None and not verdict:
				return PAYMENT_NOT_READY
		return None

	@staticmethod
	def _stock_check_enabled() -> bool:
		return cint(frappe.conf.get(STOCK_CHECK_CONFIG)) == 1

	@staticmethod
	def _stock_shortages(quotation) -> list[str]:
		"""Return the stocked rows whose warehouse cannot cover the quantity.

		Availability is ERPNext's own ``Bin.projected_qty`` for the row's
		warehouse. Non-stock items and rows without a warehouse are skipped
		(nothing to check against), so enabling the gate never fails a cart
		on missing master data.
		"""
		shortages: list[str] = []
		for row in quotation.items:
			if not cint(frappe.db.get_value("Item", row.item_code, "is_stock_item")):
				continue
			warehouse = row.get("warehouse")
			if not warehouse:
				continue
			projected = flt(
				frappe.db.get_value(
					"Bin", {"item_code": row.item_code, "warehouse": warehouse}, "projected_qty"
				)
			)
			if flt(row.qty) > projected:
				shortages.append(f"{row.item_code} ({projected} available)")
		return shortages

	def _settle(self, reference, quotation, payload: StoreCompleteCart) -> StoreCompleteCartResponse:
		"""Place the order and consume the cart's credit holds, atomically.

		Every settle write shares the caller's transaction inside the
		``SETTLE_SAVEPOINT`` savepoint, so an expected validation failure is
		rolled back to the savepoint — the Quotation submission, the Sales
		Order, the order reference and the wallet debits — while the cart
		row lock stays held, and returned as the pinned
		``OrderPlacementError`` refusal for the untouched open cart. The
		savepoint is what keeps a caught failure from committing the partial
		settle; anything wider propagates to the router's ``500``.
		"""
		frappe.db.savepoint(SETTLE_SAVEPOINT)
		try:
			order = self._place_order(reference, quotation)
		except SETTLE_EXPECTED_EXCEPTIONS as error:
			return self._placement_failed(reference, quotation, error)
		frappe.db.release_savepoint(SETTLE_SAVEPOINT)
		return StoreCompleteCartSuccess(order=order)

	def _place_order(self, reference, quotation) -> StoreOrder:
		"""Run the settle writes: submit, map, assert, book, consume."""
		with privileged_scope():
			# Medusa carts never expire; the Quotation's ERPNext validity
			# must not block a cart checked out long after creation.
			if quotation.valid_till and getdate(quotation.valid_till) < getdate(today()):
				quotation.valid_till = today()
			quotation.submit()
			sales_order = convert_quotation_to_sales_order(quotation.name, submit=True)
			self._assert_order_lines_are_cart_lines(reference, quotation, sales_order)
			order_reference = frappe.get_doc(
				{
					"doctype": "Ceto Order Reference",
					"order_id": new_order_id(),
					"sales_order": sales_order.name,
					"cart_id": reference.cart_id,
				}
			).insert(ignore_permissions=True)
			# The holds become money only once the order exists.
			CartCredits.consume_cart_credits(quotation)
		return StoreOrder.model_validate(self.orders.serialize(order_reference, sales_order, reference))

	@staticmethod
	def _assert_order_lines_are_cart_lines(reference, quotation, sales_order) -> None:
		"""Refuse the completion when a Sales Order row is not a cart line.

		The ERPNext mapper stamps every Sales Order row with its source
		Quotation Item row, and the cart's ``Ceto Cart Line Item Reference``
		rows are keyed on exactly those source rows — so every Sales Order
		row must resolve to a mapping of this cart whose source row also
		belongs to this cart's Quotation. Otherwise the serialized order
		would silently lose or invent lines; the refusal fires inside the
		settle savepoint, so nothing is ever placed half-mapped.
		"""
		mapped_sources = set(
			frappe.get_all(
				"Ceto Cart Line Item Reference",
				filters={"cart_reference": reference.name},
				pluck="quotation_item",
			)
		)
		for row in sales_order.items or []:
			source = row.get("quotation_item")
			if not source or source not in mapped_sources:
				frappe.throw(
					frappe._(
						"Sales Order row {0} has no matching cart line mapping; the order cannot be placed"
					).format(row.item_code or row.name)
				)
			if frappe.db.get_value("Quotation Item", source, "parent") != quotation.name:
				frappe.throw(
					frappe._(
						"Sales Order row {0} maps to a Quotation Item outside the cart's"
						" Quotation {1}; the order cannot be placed"
					).format(row.item_code or row.name, quotation.name)
				)

	def _placement_failed(self, reference, quotation, error: Exception) -> StoreCompleteCartFailure:
		"""Roll the settle back to its savepoint and refuse with the open cart.

		``ROLLBACK TO SAVEPOINT`` undoes the settle's writes but keeps the
		cart row lock and the request transaction. The documents are
		reloaded because the submission had already flipped the Quotation's
		docstatus on the live objects; the ERPNext reason goes to the Error
		Log for operators, the refusal carries only the stable identity.
		"""
		frappe.db.rollback(save_point=SETTLE_SAVEPOINT)
		frappe.log_error(title="Ceto cart completion settle failed", message=f"{reference.cart_id}: {error}")
		reference.reload()
		quotation.reload()
		return self._failure(reference, quotation, ORDER_PLACEMENT_FAILED)

	def _failure(self, reference, quotation, refusal: CompletionRefusal) -> StoreCompleteCartFailure:
		"""Echo the untouched open cart with the refusal's pinned error."""
		cart = StoreCart.model_validate(self.serializer.serialize(reference, quotation))
		return StoreCompleteCartFailure(
			cart=cart,
			error=StoreCompleteCartError(
				message=refusal.message,
				name=refusal.name,
				type=refusal.type,
			),
		)
