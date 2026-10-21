"""Read-only Store currency projections scoped to configured commerce.

The pinned decision (``docs/reference-data/field-mapping.md``): Ceto's
currency list is **not** the ERPNext currency table. It is exactly the
distinct currencies its servable configured commerce regions resolve to
(``RegionDirectory``), deduplicated and ordered by the lowercase Medusa
code. One ERPNext ``Currency`` powers every projection — metadata, symbol,
fraction digits and rounding are the record's own, and its ``creation`` /
``modified`` timestamps are real record timestamps, served as-is.

The routes stay masked at the configuration boundary: a currency no valid
region references is invisible to the list and ``404`` on detail, whatever
its ERPNext state. Region validity is the single gate — an ERPNext-disabled
currency that a valid region references still projects, so a master-data
flag cannot silently break the storefront's region↔currency join.
"""

import frappe

from ceto.routing.exceptions import RouteNotFoundError
from ceto.services.reference.regions import RegionDirectory
from ceto.types.http.store.currencies import (
	CURRENCY_LIST_DEFAULT_LIMIT,
	CURRENCY_LIST_DEFAULT_OFFSET,
	CURRENCY_LIST_MAX_LIMIT,
	StoreCurrency,
	StoreCurrencyListResponse,
	StoreCurrencyResponse,
)


class CurrencyDirectory:
	"""Project the currencies of the configured commerce regions."""

	def __init__(self, regions: RegionDirectory | None = None) -> None:
		self.regions = regions or RegionDirectory()

	def list(
		self,
		*,
		limit: int = CURRENCY_LIST_DEFAULT_LIMIT,
		offset: int = CURRENCY_LIST_DEFAULT_OFFSET,
	) -> StoreCurrencyListResponse:
		"""Return the pinned ``{currencies, count, offset, limit}`` envelope."""
		codes = self.referenced_codes()
		offset = max(0, int(offset))
		limit = min(max(0, int(limit)), CURRENCY_LIST_MAX_LIMIT)
		page = codes[offset : offset + limit]
		rows = self._currency_rows(page)
		return StoreCurrencyListResponse(
			currencies=[self._projection(row) for row in rows],
			count=len(codes),
			offset=offset,
			limit=limit,
		)

	def get(self, code: str) -> StoreCurrencyResponse:
		"""Return one referenced currency; unreferenced codes mask as 404."""
		normalized = (code or "").strip().lower()
		if normalized not in self.referenced_codes():
			raise RouteNotFoundError(f"Currency {normalized or '(not set)'} not found")
		rows = self._currency_rows([normalized])
		if not rows:
			raise RouteNotFoundError(f"Currency {normalized} not found")
		return StoreCurrencyResponse(currency=self._projection(rows[0]))

	def referenced_codes(self) -> list[str]:
		"""Return the distinct referenced currency codes, ordered by code."""
		codes = {region.currency_code for region in self.regions.servable()}
		return sorted(codes)

	def _currency_rows(self, codes: list[str]) -> list[dict]:
		"""Load the ERPNext ``Currency`` rows for lowercase Medusa codes."""
		if not codes:
			return []
		names = [code.upper() for code in codes]
		return frappe.get_all(
			"Currency",
			filters={"name": ("in", names)},
			fields=(
				"name",
				"currency_name",
				"symbol",
				"smallest_currency_fraction_value",
				"number_format",
				"creation",
				"modified",
			),
			order_by="name",
		)

	@staticmethod
	def _projection(row: dict) -> StoreCurrency:
		"""Project one ERPNext ``Currency`` onto the pinned entity."""
		return StoreCurrency(
			code=row.name.lower(),
			name=row.currency_name or row.name,
			symbol=row.symbol or None,
			symbol_native=None,
			decimal_digits=_fraction_digits(row.number_format),
			rounding=float(row.smallest_currency_fraction_value) or None,
			created_at=row.creation,
			updated_at=row.modified,
		)


def _fraction_digits(number_format: str | None) -> int | None:
	"""Count the fraction placeholders of an ERPNext number format.

	``#,###.##`` → 2, ``#,###.###`` → 3, ``#,###`` → 0, unset → ``None``.
	"""
	if not number_format:
		return None
	_, _, fraction = number_format.partition(".")
	return len(fraction)
