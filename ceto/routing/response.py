import json
from dataclasses import dataclass, field
from typing import Any, Self

from pydantic import BaseModel
from werkzeug.datastructures import Headers
from werkzeug.wrappers import Response


@dataclass(frozen=True)
class JSON[T]:
	"""A typed JSON result returned by a Ceto endpoint."""

	value: T
	status_code: int = 200
	headers: dict[str, str] = field(default_factory=dict)

	def to_response(self) -> Response:
		payload: Any = self.value
		if isinstance(payload, BaseModel):
			payload = payload.model_dump(mode="json")

		return Response(
			json.dumps(payload, separators=(",", ":"), default=str),
			status=self.status_code,
			headers=Headers(self.headers),
			content_type="application/json",
		)


class JSONModel(BaseModel):
	"""Pydantic model that can be returned as a typed Ceto JSON result."""

	def to_json(self, *, status_code: int = 200) -> JSON[Self]:
		return JSON(self, status_code=status_code)
