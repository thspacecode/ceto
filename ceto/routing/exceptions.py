class CetoHTTPError(Exception):
	"""Base exception rendered as a Medusa-compatible JSON error."""

	error_type = "request_error"
	status_code = 500
	default_message = "Request failed"

	def __init__(self, message: str | None = None) -> None:
		self.message = message or self.default_message
		super().__init__(self.message)

	def to_dict(self) -> dict[str, str]:
		return {"type": self.error_type, "message": self.message}


class RequestError(CetoHTTPError):
	"""Error preserving an HTTP status not covered by a specific Ceto class."""

	def __init__(self, message: str, status_code: int) -> None:
		self.status_code = status_code
		super().__init__(message)


class InvalidDataError(CetoHTTPError):
	error_type = "invalid_data"
	status_code = 400
	default_message = "Invalid request data"


class UnauthorizedError(CetoHTTPError):
	error_type = "unauthorized"
	status_code = 401
	default_message = "Authentication required"


class NotAllowedError(CetoHTTPError):
	error_type = "not_allowed"
	status_code = 403
	default_message = "Not permitted"


class RouteNotFoundError(CetoHTTPError):
	error_type = "not_found"
	status_code = 404
	default_message = "Route not found"


class MethodNotAllowedError(CetoHTTPError):
	error_type = "method_not_allowed"
	status_code = 405
	default_message = "Method not allowed"


class InternalServerError(CetoHTTPError):
	error_type = "internal_error"
	status_code = 500
	default_message = "An unexpected error occurred"
