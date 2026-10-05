"""Domain errors used by independently testable EventForge feature modules."""


class DomainError(Exception):
    """Base class for errors that routes may translate to HTTP responses."""


class ValidationError(DomainError):
    """A supplied domain value violates an invariant."""


class NotFoundError(DomainError):
    """An addressed aggregate does not exist."""


class ConflictError(DomainError):
    """An operation conflicts with existing domain state."""
