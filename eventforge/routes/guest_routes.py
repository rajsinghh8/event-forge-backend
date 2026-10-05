"""Flask blueprint for the owned event guest resource."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, request

from eventforge.errors import ValidationError
from eventforge.security import require_auth
from eventforge.services.guest_service import GuestService


def create_guest_blueprint(service: GuestService) -> Blueprint:
    """Build the guest blueprint; authentication middleware sets ``g.user_id``."""
    blueprint = Blueprint("guests", __name__)

    @blueprint.get("/events/<uuid:event_id>/guests")
    @require_auth
    def list_guests(event_id: UUID) -> Response:
        page, size, filters, sort, direction = _list_query()
        return jsonify(service.list(event_id, _user_id(), filters, page, size, sort, direction))

    @blueprint.post("/events/<uuid:event_id>/guests")
    @require_auth
    def create_guest(event_id: UUID) -> tuple[Response, int]:
        guest = service.create(event_id, _user_id(), _json_body())
        return jsonify(guest), 201

    @blueprint.get("/events/<uuid:event_id>/guests/<uuid:guest_id>")
    @require_auth
    def get_guest(event_id: UUID, guest_id: UUID) -> Response:
        return jsonify(service.get(event_id, guest_id, _user_id()))

    @blueprint.patch("/events/<uuid:event_id>/guests/<uuid:guest_id>")
    @require_auth
    def update_guest(event_id: UUID, guest_id: UUID) -> Response:
        return jsonify(service.update(event_id, guest_id, _user_id(), _json_body()))

    @blueprint.delete("/events/<uuid:event_id>/guests/<uuid:guest_id>")
    @require_auth
    def delete_guest(event_id: UUID, guest_id: UUID) -> tuple[Response, int]:
        service.delete(event_id, guest_id, _user_id())
        return "", 204

    return blueprint


def _user_id() -> UUID:
    """Accept UUID or JWT string subject while never consulting request input."""
    value = g.user_id
    return value if isinstance(value, UUID) else UUID(str(value))


def _json_body() -> dict[str, Any]:
    if not request.is_json:
        raise ValidationError("Content-Type must be application/json")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object")
    return body


def _list_query() -> tuple[int, int, dict[str, str], str, str]:
    allowed = {"page", "size", "name", "text", "status", "sort", "direction"}
    unknown = set(request.args) - allowed
    if unknown:
        raise ValidationError(f"Unknown query parameter: {sorted(unknown)[0]}")
    page = _positive_int("page", 1, maximum=1_000_000)
    size = _positive_int("size", 20, maximum=100)
    status = request.args.get("status")
    if status is not None and status not in GuestService.VALID_STATUSES:
        raise ValidationError("status must be invited, accepted, declined, or cancelled")
    filters = {key: request.args[key].strip() for key in ("name", "text") if key in request.args}
    if any(not value for value in filters.values()):
        raise ValidationError("text and name filters cannot be empty")
    if status is not None:
        filters["status"] = status
    sort = request.args.get("sort", "createdAt")
    if sort not in GuestService.SORT_COLUMNS:
        raise ValidationError("sort must be one of name, email, status, createdAt, updatedAt")
    direction = request.args.get("direction", "desc").lower()
    if direction not in {"asc", "desc"}:
        raise ValidationError("direction must be asc or desc")
    return page, size, filters, sort, direction.upper()


def _positive_int(name: str, default: int, *, maximum: int) -> int:
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValidationError(f"{name} must be an integer") from exc
    if not 1 <= value <= maximum:
        raise ValidationError(f"{name} must be between 1 and {maximum}")
    return value


# Kept as an explicit alias for application factories that use the conventional
# ``guest_blueprint(service)`` naming in their wiring module.
guest_blueprint = create_guest_blueprint
