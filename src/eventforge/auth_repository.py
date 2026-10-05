"""Persistence boundary owned by the authentication feature."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str
    display_name: str
    password_hash: str


class UserRepository(Protocol):
    """Repository operations required by :class:`AuthService`."""

    def find_by_email(self, email: str) -> AuthUser | None: ...

    def create_user(self, *, email: str, display_name: str, password_hash: str) -> AuthUser: ...
