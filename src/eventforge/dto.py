"""Public authentication request and response DTOs."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RegisterRequest:
    email: str
    password: str
    display_name: str


@dataclass(frozen=True)
class LoginRequest:
    email: str
    password: str


@dataclass(frozen=True)
class UserDTO:
    id: str
    email: str
    display_name: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class AuthTokenDTO:
    access_token: str
    token_type: str
    expires_in: int
    user: UserDTO

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "user": self.user.to_dict()}
