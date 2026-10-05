from __future__ import annotations
from dataclasses import dataclass

@dataclass
class DomainError(Exception):
    message: str
    status_code: int = 400
class ValidationError(DomainError):
    def __init__(self, message: str): super().__init__(message, 400)
class AuthenticationError(DomainError):
    def __init__(self, message: str = "Authentication required"): super().__init__(message, 401)
class AuthorizationError(DomainError):
    def __init__(self, message: str = "Forbidden"): super().__init__(message, 403)
class NotFoundError(DomainError):
    def __init__(self, message: str = "Resource not found"): super().__init__(message, 404)
class ConflictError(DomainError):
    def __init__(self, message: str): super().__init__(message, 409)
