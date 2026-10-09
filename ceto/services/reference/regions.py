"""Read-only Store region projections backed by the cart region config.

Ceto's regions are the ``ceto_cart.regions`` site configuration — no
``Region`` DocType exists and none is introduced. A region is **servable**
(the only regions this module lists or resolves) when its *effective*
configuration — the top-level ``ceto_cart`` defaults overlaid by the region
entry, exactly the overlay ``CartConfiguration.resolve`` applies — resolves
all three commerce anchors in ERPNext: an existing Company, an existing
selling Price List, and a currency (the entry's ``currency`` key, else the
price list currency — the identical resolution rule the cart service uses,
shared through :mod:`ceto.config.cart`). An explicit currency conflicting
with the Price List's own resolves nothing a cart could serve (carts price
in the Price List's currency), so the region is unservable like any other
broken anchor. A misconfigured region is not an
error: it is invisible to the list and masked as ``404`` on detail, so a
broken overlay can never surface a region no cart could use.

The projections are deterministic: regions order by region id, pages echo
the effective ``offset`` / ``limit`` bounded by the pinned manifest
constants, and the count runs over the servable set before pagination.
Config-backed regions carry no record timestamps, so ``created_at`` /
``updated_at`` stay ``None`` — never fabricated.
"""

from typing import Any

import frappe

from ceto.config.cart import cart_settings, region_entries
from ceto.routing.exceptions import RouteNotFoundError
from ceto.types.http.store.regions import (
	REGION_LIST_DEFAULT_LIMIT,
	REGION_LIST_DEFAULT_OFFSET,
	REGION_LIST_MAX_LIMIT,
	StoreRegion,
	StoreRegionListResponse,
	StoreRegionResponse,
)


class RegionDirectory:
	"""Project the configured commerce regions as pinned Store regions."""

	def list(
		self,
		*,
		limit: int = REGION_LIST_DEFAULT_LIMIT,
		offset: int = REGION_LIST_DEFAULT_OFFSET,
	) -> StoreRegionListResponse:
		"""Return the pinned ``{regions, count, offset, limit}`` envelope."""
		regions = self.servable()
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), REGION_LIST_MAX_LIMIT)
		page = regions[offset : offset + limit]
		return StoreRegionListResponse(
			regions=page,
			count=len(regions),
			offset=offset,
			limit=limit,
		)

	def servable(self) -> list[StoreRegion]:
		"""Return every servable region projection, ordered by region id."""
		servable = self._servable_map(cart_settings())
		return [StoreRegion(**servable[region_id]) for region_id in sorted(servable)]

	def get(self, region_id: str) -> StoreRegionResponse:
		"""Return one servable region; unknown or invalid ids mask as 404."""
		region = self._servable_map(cart_settings()).get(region_id)
		if region is None:
			raise RouteNotFoundError(f"Region {region_id or '(not set)'} not found")
		return StoreRegionResponse(region=StoreRegion(**region))

	def _servable_map(self, settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
		"""Resolve every configured region to its projection, dropping invalid ones."""
		entries = region_entries(settings)
		effective = {}
		for region_id, entry in entries.items():
			merged = dict(settings)
			merged.update(entry if isinstance(entry, dict) else {})
			effective[region_id] = merged

		companies = _existing("Company", [row.get("company") for row in effective.values()])
		price_lists = _price_list_currencies([row.get("selling_price_list") for row in effective.values()])
		currencies = _existing("Currency", [*price_lists.values()])

		servable = {}
		for region_id, merged in effective.items():
			company = merged.get("company")
			price_list = merged.get("selling_price_list")
			if not company or company not in companies:
				continue
			if not price_list or price_list not in price_lists:
				continue
			price_list_currency = price_lists[price_list]
			currency = merged.get("currency") or price_list_currency
			if not currency or currency not in currencies:
				continue
			# Carts price in their Price List's own currency (the quotation
			# pins conversion_rate/plc_conversion_rate at 1), so an explicit
			# currency conflicting with the Price List resolves no usable
			# cart: the region is unservable, masked like any broken anchor.
			if merged.get("currency") and currency != price_list_currency:
				continue
			servable[region_id] = self._projection(region_id, merged, currency)
		return servable

	@staticmethod
	def _projection(region_id: str, entry: dict[str, Any], currency: str) -> dict[str, Any]:
		return {
			"id": region_id,
			"name": entry.get("name") or region_id,
			"currency_code": currency.lower(),
			"automatic_taxes": True,
			"countries": None,
			"metadata": None,
			"created_at": None,
			"updated_at": None,
		}


def _existing(doctype: str, names: list[Any]) -> set[str]:
	"""Return the subset of names that exist as records of ``doctype``."""
	candidates = {str(name) for name in names if name}
	if not candidates:
		return set()
	rows = frappe.get_all(doctype, filters={"name": ("in", sorted(candidates))}, pluck="name")
	return set(rows)


def _price_list_currencies(names: list[Any]) -> dict[str, str]:
	"""Map each existing selling Price List name to its currency."""
	candidates = {str(name) for name in names if name}
	if not candidates:
		return {}
	rows = frappe.get_all(
		"Price List",
		filters={"name": ("in", sorted(candidates))},
		fields=("name", "currency"),
	)
	return {row.name: row.currency for row in rows}
