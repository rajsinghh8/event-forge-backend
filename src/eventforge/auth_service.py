"""Application service for registration and credential login."""

from __future__ import annotations

import re
from typing import Protocol

from .auth_repository import AuthUser, UserRepository
from .dto import AuthTokenDTO, LoginRequest, RegisterRequest, UserDTO
from .errors import AuthenticationError, ConflictError, ValidationError
from .security import JwtCodec, PasswordHasher

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthSettings(Protocol):
    jwt_secret: str
    jwt_issuer: str
    jwt_ttl_seconds: int


class AuthService:
    """Coordinates validation, persistence, password hashing, and token minting."""

    def __init__(self, repository: UserRepository, settings: AuthSettings, *, hasher: PasswordHasher | None = None) -> None:
        self._repository = repository
        self._hasher = hasher or PasswordHasher()
        self._jwt = JwtCodec(settings.jwt_secret, settings.jwt_issuer, settings.jwt_ttl_seconds)

    def register(self, request: RegisterRequest) -> AuthTokenDTO:
        email = self._validate_email(request.email)
        display_name = self._validate_display_name(request.display_name)
        self._validate_password(request.password)
        if self._repository.find_by_email(email) is not None:
            raise ConflictError("An account with this email already exists")
        user = self._repository.create_user(
            email=email,
            display_name=display_name,
            password_hash=self._hasher.hash(request.password),
        )
        return self._token_response(user)

    def login(self, request: LoginRequest) -> AuthTokenDTO:
        email = self._validate_email(request.email)
        if not isinstance(request.password, str) or not request.password:
            raise AuthenticationError()
        user = self._repository.find_by_email(email)
        if user is None or not self._hasher.verify(request.password, user.password_hash):
            raise AuthenticationError()
        return self._token_response(user)

    def _token_response(self, user: AuthUser) -> AuthTokenDTO:
        return AuthTokenDTO(
            access_token=self._jwt.issue(user.id),
            token_type="Bearer",
            expires_in=self._jwt.ttl_seconds,
            user=UserDTO(id=user.id, email=user.email, display_name=user.display_name),
        )

    @staticmethod
    def _validate_email(value: str) -> str:
        if not isinstance(value, str):
            raise ValidationError("Email is required")
        email = value.strip().lower()
        if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
            raise ValidationError("Email must be a valid address")
        return email

    @staticmethod
    def _validate_display_name(value: str) -> str:
        if not isinstance(value, str):
            raise ValidationError("Display name is required")
        name = value.strip()
        if not 1 <= len(name) <= 100:
            raise ValidationError("Display name must be between 1 and 100 characters")
        return name

    @staticmethod
    def _validate_password(value: str) -> None:
        if not isinstance(value, str) or len(value) < 8:
            raise ValidationError("Password must be at least 8 characters")
        if len(value) > 1024:
            raise ValidationError("Password is too long")
