"""Pinned ``StoreRegion`` entity contract.

Mirrors ``http/region/store`` of ``@medusajs/types@2.21.1`` for the columns
Ceto can project from its configuration-backed regions
(``ceto.services.reference.regions``):

- ``created_at`` / ``updated_at`` stay optional and are left ``None`` on
  purpose — a config-backed region has no record timestamps, and Ceto never
  fabricates them.
- ``countries`` mirrors the pinned optional relation but is never populated
  in slice A: the region configuration carries no country list (deliberate
  omission, ``docs/reference-data/field-mapping.md``).
- ``payment_providers`` is dropped entirely: no payment-provider projection
  exists in Ceto yet.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StoreRegionCountry(BaseModel):
	"""Medusa ``StoreRegionCountry`` entity (pinned baseline fields)."""

	id: str
	iso_2: str | None = None
	iso_3: str | None = None
	num_code: str | None = None
	name: str | None = None
	display_name: str | None = None


class StoreRegion(BaseModel):
	"""Medusa ``StoreRegion`` shape (Phase 1 subset).

	``automatic_taxes`` projects a Ceto behavioral invariant, not config
	state: ERPNext Selling documents always recalculate their tax template
	on save, so region taxes are always automatic.
	"""

	id: str
	name: str
	currency_code: str
	automatic_taxes: bool = True
	countries: list[StoreRegionCountry] | None = None
	metadata: dict[str, Any] | None = None
	created_at: datetime | None = None
	updated_at: datetime | None = None
