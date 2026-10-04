"""Store order HTTP surface: the thin adapter over ``OrderService``.

Phase 2 wires the pinned retrieve route only; the boundary tests prove the
list and transfer routes stay contract-only until their phase registers
them.
"""

from typing import Any

from ceto.api.store.publishable_key import CartPublishableKey
from ceto.routing import ceto_router
from ceto.services.orders.service import OrderService


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
