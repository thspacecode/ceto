"""Pinned ``StoreCurrency`` entity contract.

Mirrors ``http/currency/store`` of ``@medusajs/types@2.21.1`` for the columns
Ceto can project from the ERPNext ``Currency`` records its valid configured
commerce regions reference (``ceto.services.reference.currencies``):

- ``code`` carries Medusa's lowercase convention; ERPNext names the record
  with the uppercase ISO code.
- ``symbol_native`` stays optional and is left ``None`` on purpose — ERPNext
  stores one symbol per currency, no native-vs-plain distinction, and Ceto
  never fabricates the difference.
- ``rounding`` projects the ERPNext ``smallest_currency_fraction_value``
  (the currency's own smallest fraction, unset stays ``None``).
- ``decimal_digits`` derives from the ERPNext ``number_format`` fraction
  placeholders (``#,###.##`` → 2, ``#,###`` → 0).
- ``created_at`` / ``updated_at`` are real record timestamps (ERPNext
  ``creation`` / ``modified``) — unlike the config-backed regions, these are
  never ``None`` by policy.
- ``deleted_at`` stays optional and is never populated: ERPNext deletes
  currencies hard, there is no soft-delete tombstone to project.
"""

from datetime import datetime

from pydantic import BaseModel


class StoreCurrency(BaseModel):
	"""Medusa ``StoreCurrency`` shape (Phase 1 subset)."""

	code: str
	name: str
	symbol: str | None = None
	symbol_native: str | None = None
	decimal_digits: int | None = None
	rounding: float | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
	deleted_at: datetime | None = None
