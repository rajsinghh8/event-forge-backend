"""Domain-level errors and their HTTP representation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar


@dataclass(eq=False)
class DomainError(Exception):
    """A safe error that may be exposed to an API client."""

    message: str
    code: str = "domain_error"
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


class ValidationError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "validation_error", 400)


class AuthenticationError(DomainError):
    def __init__(self, message: str = "Invalid email or password") -> None:
        super().__init__(message, "authentication_failed", 401)


class ConflictError(DomainError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "conflict", 409)


def domain_error_payload(error: DomainError) -> dict[str, str]:
    """Return the stable public error body used by route handlers."""
    return {"error": error.code, "message": error.message}


F = TypeVar("F", bound=Callable[..., Any])


def map_domain_errors(handler: F) -> F:
    """Mark a route handler for central domain error mapping.

    The returned wrapper deliberately imports Bottle only when a route is
    invoked, allowing domain and service code to remain framework independent.
    """
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return handler(*args, **kwargs)
        except DomainError as error:
            from bottle import HTTPResponse

            return HTTPResponse(
                status=error.status_code,
                body=domain_error_payload(error),
            )

    return wrapped  # type: ignore[return-value]
