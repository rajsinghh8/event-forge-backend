"""Bottle route registrar for public authentication endpoints."""

from __future__ import annotations

from typing import Any, Mapping

from .auth_service import AuthService
from .dto import LoginRequest, RegisterRequest
from .errors import ValidationError, map_domain_errors


def _json_object(request: Any) -> Mapping[str, Any]:
    payload = request.json
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    return payload


def _string(payload: Mapping[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str):
        raise ValidationError(f"{name.replace('_', ' ').capitalize()} is required")
    return value


def register_auth_routes(app: Any, service: AuthService) -> None:
    """Attach ``POST /auth/register`` and ``POST /auth/login`` to a Bottle app."""
    # Bottle is purposefully not imported at module import time. This keeps
    # auth domain code usable in unit tests and non-HTTP contexts.
    from bottle import request

    @app.post("/auth/register")
    @map_domain_errors
    def register() -> dict[str, object]:
        payload = _json_object(request)
        result = service.register(RegisterRequest(
            email=_string(payload, "email"),
            password=_string(payload, "password"),
            display_name=_string(payload, "display_name"),
        ))
        return result.to_dict()

    @app.post("/auth/login")
    @map_domain_errors
    def login() -> dict[str, object]:
        payload = _json_object(request)
        result = service.login(LoginRequest(
            email=_string(payload, "email"),
            password=_string(payload, "password"),
        ))
        return result.to_dict()
