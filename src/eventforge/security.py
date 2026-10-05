"""Dependency-free password and JWT primitives for EventForge."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import AuthenticationError, ValidationError


_PASSWORD_SCHEME = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 310_000


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, UnicodeEncodeError) as exc:
        raise AuthenticationError("Invalid token") from exc


@dataclass(frozen=True)
class PasswordHasher:
    """PBKDF2-SHA256 password hashes with independent random salts."""

    iterations: int = _DEFAULT_ITERATIONS
    salt_bytes: int = 16

    def __post_init__(self) -> None:
        if self.iterations < 1 or self.salt_bytes < 16:
            raise ValueError("PBKDF2 requires positive iterations and a 16-byte salt")

    def hash(self, password: str) -> str:
        if not isinstance(password, str) or not password:
            raise ValidationError("Password is required")
        salt = secrets.token_bytes(self.salt_bytes)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, self.iterations)
        return f"{_PASSWORD_SCHEME}${self.iterations}${_b64encode(salt)}${_b64encode(digest)}"

    def verify(self, password: str, encoded_hash: str) -> bool:
        if not isinstance(password, str) or not isinstance(encoded_hash, str):
            return False
        try:
            scheme, iteration_text, salt_text, digest_text = encoded_hash.split("$")
            if scheme != _PASSWORD_SCHEME:
                return False
            iterations = int(iteration_text)
            if iterations < 1:
                return False
            salt, expected = _b64decode(salt_text), _b64decode(digest_text)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, AuthenticationError):
            return False


@dataclass(frozen=True)
class JwtClaims:
    subject: str
    issued_at: int
    expires_at: int


@dataclass(frozen=True)
class JwtCodec:
    """Minimal HS256 JWT codec. Tokens contain only standard auth claims."""

    secret: str
    issuer: str = "eventforge"
    ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if not isinstance(self.secret, str) or not self.secret:
            raise ValueError("JWT secret must not be empty")
        if not isinstance(self.issuer, str) or not self.issuer:
            raise ValueError("JWT issuer must not be empty")
        if not isinstance(self.ttl_seconds, int) or self.ttl_seconds <= 0:
            raise ValueError("JWT TTL must be positive")

    def issue(self, subject: str, *, now: int | None = None) -> str:
        if not isinstance(subject, str) or not subject:
            raise ValueError("JWT subject must not be empty")
        issued_at = int(time.time() if now is None else now)
        header = _b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _b64encode(json.dumps({"sub": subject, "iss": self.issuer, "iat": issued_at, "exp": issued_at + self.ttl_seconds}, separators=(",", ":")).encode())
        signing_input = f"{header}.{payload}".encode("ascii")
        signature = _b64encode(hmac.new(self.secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
        return f"{header}.{payload}.{signature}"

    def validate(self, token: str, *, now: int | None = None) -> JwtClaims:
        if not isinstance(token, str):
            raise AuthenticationError("Invalid token")
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("Invalid token")
        header_text, payload_text, signature_text = parts
        try:
            signing_input = f"{header_text}.{payload_text}".encode("ascii")
            expected = hmac.new(self.secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _b64decode(signature_text)):
                raise AuthenticationError("Invalid token")
            header: Mapping[str, Any] = json.loads(_b64decode(header_text))
            payload: Mapping[str, Any] = json.loads(_b64decode(payload_text))
            if header.get("alg") != "HS256" or header.get("typ") != "JWT":
                raise ValueError("invalid header")
            subject, issuer = payload["sub"], payload["iss"]
            issued_at, expires_at = payload["iat"], payload["exp"]
            if not isinstance(subject, str) or not subject or issuer != self.issuer:
                raise ValueError("invalid claims")
            if type(issued_at) is not int or type(expires_at) is not int:
                raise ValueError("invalid timestamps")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, AuthenticationError) as exc:
            raise AuthenticationError("Invalid token") from exc
        current_time = int(time.time() if now is None else now)
        if expires_at <= current_time:
            raise AuthenticationError("Token has expired")
        return JwtClaims(subject=subject, issued_at=issued_at, expires_at=expires_at)
