"""Domain errors and the one EventForge JSON error envelope."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any

class ApiError(Exception):
    status_code = 400
    error = "Bad Request"
    def __init__(self, message: str) -> None:
        super().__init__(message); self.message = message
class ValidationError(ApiError): status_code, error = 422, "Validation Error"
class AuthenticationError(ApiError): status_code, error = 401, "Unauthorized"
class ForbiddenError(ApiError): status_code, error = 403, "Forbidden"
class NotFoundError(ApiError): status_code, error = 404, "Not Found"
class BusinessRuleError(ApiError): status_code, error = 409, "Conflict"
class ConflictError(BusinessRuleError): pass

def error_body(error: ApiError, path: str) -> dict[str, Any]:
    return {"timestamp": datetime.now(UTC).isoformat(), "status": error.status_code,
            "error": error.error, "message": error.message, "path": path}
def write_error_response(handler: Any, error: ApiError) -> None:
    handler.set_status(error.status_code); handler.set_header("Content-Type", "application/json")
    handler.finish(error_body(error, handler.request.path))
