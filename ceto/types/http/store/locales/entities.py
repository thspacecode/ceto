"""Pinned ``StoreLocale`` entity contract.

Mirrors ``http/locale/store`` of ``@medusajs/types@2.21.1`` exactly: the
pinned entity carries only ``code`` and ``name``, so Ceto's projection of the
enabled Frappe ``Language`` records adds nothing per locale. The extension
lives one level up, on the list response (``default_locale``).
"""

from pydantic import BaseModel


class StoreLocale(BaseModel):
	"""Medusa ``StoreLocale`` entity (pinned in full)."""

	code: str
	name: str
