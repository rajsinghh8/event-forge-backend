"""Authenticated HTTP endpoints for the task resource."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Any
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

try:  # Allows feature-module imports before the auth unit is assembled.
    from eventforge.auth import require_auth
except ImportError:  # pragma: no cover
    def require_auth(function):
        return function

from .service import TaskError, TaskService


task_bp = Blueprint("tasks", __name__, url_prefix="/tasks")
# Alias keeps blueprint naming consistent for callers that use plural modules.
tasks_bp = task_bp


def _service() -> TaskService:
    services = current_app.extensions["services"]
    if isinstance(services, dict):
        service = services.get("task_service") or services.get("tasks") or services.get("task")
    else:
        service = (getattr(services, "task_service", None) or getattr(services, "tasks", None)
                   or getattr(services, "task", None))
    if service is None and isinstance(services, dict) and services.get("database") is not None:
        service = TaskService(services["database"])
    if service is None:
        raise RuntimeError("TaskService is not registered in app.extensions['services']")
    return service


def _json(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    if isinstance(value, (UUID, datetime, date, Decimal)):
        return str(value) if isinstance(value, (UUID, Decimal)) else value.isoformat()
    # psycopg's dict_row is expected, but accepting a mapping-like row improves
    # compatibility with custom database adapters.
    if hasattr(value, "keys"):
        return {key: _json(value[key]) for key in value.keys()}
    return value


def _errors(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        try:
            return handler(*args, **kwargs)
        except TaskError as exc:
            return jsonify({"error": str(exc)}), exc.status_code
    return wrapped


@task_bp.post("")
@require_auth
@_errors
def create_task():
    payload = request.get_json(silent=True)
    task = _service().create(payload, g.user_id)
    return jsonify(_json(task)), 201


@task_bp.get("")
@require_auth
@_errors
def list_tasks():
    items, total, page, size = _service().list(request.args.to_dict(flat=True))
    return jsonify({"items": _json(items), "total": total, "page": page, "size": size})


@task_bp.get("/<task_id>")
@require_auth
@_errors
def get_task(task_id: str):
    return jsonify(_json(_service().get(task_id)))


@task_bp.patch("/<task_id>")
@require_auth
@_errors
def update_task(task_id: str):
    payload = request.get_json(silent=True)
    return jsonify(_json(_service().update(task_id, payload, g.user_id)))


@task_bp.delete("/<task_id>")
@require_auth
@_errors
def delete_task(task_id: str):
    _service().delete(task_id, g.user_id)
    return "", 204


# Event-scoped routes are the public resource contract.  The unscoped forms
# above remain useful to internal clients that already include event_id in the
# request, while these routes enforce ownership at the resource boundary.
def _event_task(service: TaskService, event_id: str, task_id: str) -> Any:
    service.assert_event_owner(event_id, g.user_id)
    task = service.get(task_id)
    if str(service._value(task, "event_id")) != event_id:
        from .service import NotFound
        raise NotFound("task not found")
    return task


@task_bp.get("/events/<event_id>/tasks")
@require_auth
@_errors
def list_event_tasks(event_id: str):
    service = _service()
    service.assert_event_owner(event_id, g.user_id)
    query = request.args.to_dict(flat=True)
    query["event_id"] = event_id
    items, total, page, size = service.list(query)
    return jsonify({"items": _json(items), "total": total, "page": page, "size": size})


@task_bp.post("/events/<event_id>/tasks")
@require_auth
@_errors
def create_event_task(event_id: str):
    service = _service()
    service.assert_event_owner(event_id, g.user_id)
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        from .service import ValidationError
        raise ValidationError("JSON object required")
    payload = {**payload, "event_id": event_id}
    return jsonify(_json(service.create(payload, g.user_id))), 201


@task_bp.get("/events/<event_id>/tasks/<task_id>")
@require_auth
@_errors
def get_event_task(event_id: str, task_id: str):
    return jsonify(_json(_event_task(_service(), event_id, task_id)))


@task_bp.patch("/events/<event_id>/tasks/<task_id>")
@require_auth
@_errors
def update_event_task(event_id: str, task_id: str):
    service = _service()
    _event_task(service, event_id, task_id)
    return jsonify(_json(service.update(task_id, request.get_json(silent=True), g.user_id)))


@task_bp.delete("/events/<event_id>/tasks/<task_id>")
@require_auth
@_errors
def delete_event_task(event_id: str, task_id: str):
    service = _service()
    _event_task(service, event_id, task_id)
    service.delete(task_id, g.user_id)
    return "", 204
