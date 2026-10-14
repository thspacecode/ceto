"""Region-aware product pricing over the cart price-list authority.

Products price exactly like carts: a presented ``region_id`` resolves
through :class:`~ceto.services.carts.configuration.CartConfiguration` —
the same overlay of the ``ceto_cart`` defaults with the region entry — so
the served price is always a rate on the region's selling Price List in
that Price List's own currency (carts pin the conversion at 1). An unknown
or misconfigured region raises the same ``invalid_data`` refusal a cart
create would, and a deployment that cannot resolve the cart anchors cannot
price products either. No ``region_id`` means no pricing: the projection
serves ``calculated_price`` as absent instead of guessing a default.

The Item Price read is the batched, anonymous equivalent of ERPNext's
``get_item_price`` — the resolution a cart line walks when it prices a
row: one page-wide query selects the blank-party, blank-batch rows of the
price list whose validity window contains today, newest ``valid_from``
first, a non-blank UOM outranking the unset fallback, with the row name
breaking ties Ceto-side so the selection stays deterministic. Unlike a
cart, the read is anonymous — no guest customer context exists on a
product read — so party-scoped rows never serve; carts may still resolve
them for their guest customer. An item without a surviving row is
unpriced: ``calculated_price`` stays absent, never a fabricated zero.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import frappe
from frappe.query_builder.functions import IfNull

from ceto.services.carts.configuration import CartConfiguration
from ceto.types.http.store.products import StoreCalculatedPrice

#: The open-ended validity bounds ERPNext's ``get_item_price`` substitutes
#: for unset ``valid_from`` / ``valid_upto`` — mirrored verbatim so the
#: batched selection can never disagree with the cart path on boundary rows.
VALID_FROM_FLOOR = "2000-01-01"
VALID_UPTO_CEILING = "2500-12-31"


@dataclass(frozen=True, slots=True)
class PricingAuthority:
	"""The price list and currency a region's prices resolve against."""

	region_id: str
	selling_price_list: str
	currency: str


def resolve_pricing_authority(region_id: str | None) -> PricingAuthority | None:
	"""Resolve an explicit ``region_id`` through the cart authority, or ``None``.

	A blank value is no pricing context at all — the projection serves
	unpriced instead of falling back to the cart's default region, so a
	plain list read never pays for pricing it did not ask for. A non-blank
	value must resolve the same anchors a cart create resolves; every
	refusal is the cart configuration's own ``invalid_data`` error.
	"""
	if not region_id or not str(region_id).strip():
		return None
	configuration = CartConfiguration.resolve(region_id=str(region_id).strip())
	return PricingAuthority(
		region_id=configuration.region_id,
		selling_price_list=configuration.selling_price_list,
		currency=configuration.currency,
	)


def calculate_prices(
	stock_uoms: Mapping[str, str | None], authority: PricingAuthority
) -> dict[str, StoreCalculatedPrice]:
	"""Batch-load one page's selling rates: item code → ``StoreCalculatedPrice``.

	One query covers every requested item code — the read never degrades
	into per-item lookups. The first surviving row per code wins, ordered
	like ``get_item_price``; the amount is the price list rate served as
	both the calculated and the original amount (no product-read
	adjustment exists), in the price list's own currency.
	"""
	codes = sorted(code for code in stock_uoms if code)
	stock_uom_by_code = {code: stock_uoms[code] or "" for code in codes}
	rows = _selling_rate_rows(codes, sorted({uom for uom in stock_uom_by_code.values() if uom}), authority)
	prices: dict[str, StoreCalculatedPrice] = {}
	for row in rows:
		if row.item_code in prices or not _accepts(row, stock_uom_by_code[row.item_code]):
			continue
		prices[row.item_code] = _projection(row.price_list_rate, authority)
	return prices


def _selling_rate_rows(codes: Sequence[str], uoms: Sequence[str], authority: PricingAuthority) -> list[Any]:
	"""Select the anonymous selling rows for one page, cart ordering kept.

	The UOM set is the page's union of stock UOMs so the batch stays one
	query; ``_accepts`` re-applies the per-item acceptance
	``get_item_price`` uses (the item's own stock UOM or an unset UOM).
	"""
	item_price = frappe.qb.DocType("Item Price")
	today = frappe.utils.today()
	return (
		frappe.qb.from_(item_price)
		.select(item_price.item_code, item_price.uom, item_price.price_list_rate)
		.where(
			(item_price.price_list == authority.selling_price_list)
			& (item_price.item_code.isin(list(codes)))
			& (IfNull(item_price.uom, "").isin(["", *uoms]))
			& (IfNull(item_price.batch_no, "") == "")
			& (IfNull(item_price.customer, "") == "")
			& (IfNull(item_price.supplier, "") == "")
			& (IfNull(item_price.valid_from, VALID_FROM_FLOOR) <= today)
			& (IfNull(item_price.valid_upto, VALID_UPTO_CEILING) >= today)
		)
		.orderby(item_price.valid_from, order=frappe.qb.desc)
		.orderby(item_price.uom, order=frappe.qb.desc)
		.orderby(item_price.name, order=frappe.qb.asc)
		.run(as_dict=True)
	)


def _accepts(row: Any, stock_uom: str) -> bool:
	"""Whether one rate row prices this item: its stock UOM or an unset UOM."""
	return not row.uom or row.uom == stock_uom


def _projection(rate: Any, authority: PricingAuthority) -> StoreCalculatedPrice:
	"""Project one price-list rate onto the pinned calculated-price shape.

	The flags are facts of the selection, not guesses: the amount is a
	selling Price List rate (never a promotion-adjusted price — promotions
	apply on carts), and list rates are tax-exclusive — taxes are computed
	by ERPNext controllers on the cart endpoints, never baked into a read.
	"""
	amount = float(rate)
	return StoreCalculatedPrice(
		is_calculated_price_price_list=True,
		is_calculated_price_tax_inclusive=False,
		calculated_amount=amount,
		is_original_price_price_list=True,
		is_original_price_tax_inclusive=False,
		original_amount=amount,
		currency_code=authority.currency.lower(),
		is_calculated_price_promotion=False,
	)
