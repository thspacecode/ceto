import secrets
from dataclasses import dataclass
from typing import Any, Self

import frappe

from ceto.routing.exceptions import NotAllowedError, UnauthorizedError
from ceto.types.http.store.carts import StoreCreateCart, StoreUpdateCart


@dataclass(frozen=True)
class CartPublishableKey:
	region_id: str | None = None
	sales_channel_id: str | None = None

	@classmethod
	def from_request(cls) -> Self:
		provided = frappe.request.headers.get("x-publishable-api-key", "")
		settings = frappe.conf.get("ceto_cart") or {}
		configured = settings.get("publishable_keys") or {}
		for key, scope in configured.items():
			if secrets.compare_digest(str(provided), str(key)):
				scope = dict(scope or {})
				return cls(
					region_id=scope.get("region_id"),
					sales_channel_id=scope.get("sales_channel_id"),
				)
		raise UnauthorizedError("Invalid publishable API key")

	def apply_create_defaults(self, payload: StoreCreateCart) -> StoreCreateCart:
		updates: dict[str, Any] = {}
		if payload.region_id is None and self.region_id:
			updates["region_id"] = self.region_id
		if payload.sales_channel_id is None and self.sales_channel_id:
			updates["sales_channel_id"] = self.sales_channel_id
		payload = payload.model_copy(update=updates)
		self.check_values(payload.region_id, payload.sales_channel_id)
		return payload

	def check_update(self, payload: StoreUpdateCart) -> None:
		fields = payload.model_fields_set
		self.check_values(
			payload.region_id if "region_id" in fields else None,
			payload.sales_channel_id if "sales_channel_id" in fields else None,
		)

	def check_reference(self, reference) -> None:
		self.check_values(reference.region_id or None, reference.sales_channel_id or None)

	def check_values(self, region_id: str | None, sales_channel_id: str | None) -> None:
		if self.region_id and region_id and region_id != self.region_id:
			raise NotAllowedError("Publishable API key cannot access this cart region")
		if self.sales_channel_id and sales_channel_id and sales_channel_id != self.sales_channel_id:
			raise NotAllowedError("Publishable API key cannot access this sales channel")
