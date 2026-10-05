"""Flask blueprint for the ScheduleItem resource group."""
from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, g, jsonify, request

from .errors import AuthenticationError, ValidationError
from .schedule_repository import ScheduleRepository
from .schedule_service import ScheduleService
from .security import require_auth


def create_schedule_blueprint(database: Any, service: ScheduleService | None = None) -> Blueprint:
    """Build schedule routes with explicit Database injection.

    Authentication middleware is responsible for assigning the verified JWT
    subject to ``g.user_id``.  This module never accepts an owner id from a
    path, query string, or JSON payload.
    """
    schedule_service = service or ScheduleService(database, ScheduleRepository(database))
    blueprint = Blueprint("schedule_items", __name__)

    def user_id() -> Any:
        value = getattr(g, "user_id", None)
        if value is None:
            raise AuthenticationError("Authentication required")
        return value

    def body() -> dict[str, Any]:
        parsed = request.get_json(silent=True)
        if not isinstance(parsed, dict):
            raise ValidationError("Request body must be a JSON object")
        return parsed

    @blueprint.get("/events/<uuid:event_id>/schedule-items")
    @require_auth
    def list_schedule_items(event_id: str) -> Response:
        allowed = {"page", "size", "sort", "text", "name", "startDate", "endDate"}
        unknown = set(request.args) - allowed
        if unknown:
            raise ValidationError(f"Unknown query parameter: {sorted(unknown)[0]}")
        return jsonify(schedule_service.list(user_id(), event_id, request.args.to_dict(flat=True)))

    @blueprint.post("/events/<uuid:event_id>/schedule-items")
    @require_auth
    def create_schedule_item(event_id: str) -> tuple[Response, int]:
        return jsonify(schedule_service.create(user_id(), event_id, body())), 201

    @blueprint.get("/events/<uuid:event_id>/schedule-items/<uuid:schedule_item_id>")
    @require_auth
    def get_schedule_item(event_id: str, schedule_item_id: str) -> Response:
        return jsonify(schedule_service.get(user_id(), event_id, schedule_item_id))

    @blueprint.patch("/events/<uuid:event_id>/schedule-items/<uuid:schedule_item_id>")
    @require_auth
    def update_schedule_item(event_id: str, schedule_item_id: str) -> Response:
        return jsonify(schedule_service.update(user_id(), event_id, schedule_item_id, body()))

    @blueprint.delete("/events/<uuid:event_id>/schedule-items/<uuid:schedule_item_id>")
    @require_auth
    def delete_schedule_item(event_id: str, schedule_item_id: str) -> tuple[Response, int]:
        schedule_service.delete(user_id(), event_id, schedule_item_id)
        return "", 204

    return blueprint


# Alias retained for application factories that use ``*_blueprint`` naming.
schedule_blueprint = create_schedule_blueprint
