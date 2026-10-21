"""Read-only reference-data projections for the Store surface.

Regions, currencies and locales are the storefront's reference data: the
lists a storefront needs before it can transact. Ceto projects them from
its own configuration and the ERPNext/Frappe masters — no reference
``DocType`` is introduced — and every projection here is read-only.
"""

from ceto.services.reference.currencies import CurrencyDirectory
from ceto.services.reference.locales import LocaleDirectory
from ceto.services.reference.regions import RegionDirectory

__all__ = ["CurrencyDirectory", "LocaleDirectory", "RegionDirectory"]
