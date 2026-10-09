"""Pinned query contract of the Store Locale route.

Upstream pins no query contract for ``GET /store/locales`` — the route is
unpaged and the manifest records ``query_type: None``, exactly like the
customers delete route. The unpaged list therefore still validates its
query: the model accepts nothing and forbids everything, so every key —
including a ``fields`` selector the fixed envelope never applies — is
refused as ``400 invalid_data`` instead of silently ignored.
"""

from pydantic import BaseModel, ConfigDict


class StoreLocaleListParams(BaseModel):
	"""Query of ``GET /store/locales`` (accepts nothing, forbids everything)."""

	model_config = ConfigDict(extra="forbid")
