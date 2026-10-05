"""Authenticated, event-scoped HTTP endpoints for tasks."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from functools import wraps
from typing import Any
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request

from eventforge.security import require_auth
from .service import TaskError, TaskService

# The application factory supplies /events/<event_id>/tasks.  Keeping this
# blueprint prefix-free prevents /tasks or duplicated event path segments.
task_bp = Blueprint("tasks", __name__)
tasks_bp = task_bp


def _service() -> TaskService:
    services = current_app.extensions["services"]
    service = services.get("task_service") if isinstance(services, dict) else getattr(services, "task_service", None)
    if service is None:
        raise RuntimeError("TaskService is not registered in app.extensions['services']")
    return service


def _json(value: Any) -> Any:
    if isinstance(value, dict): return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)): return [_json(item) for item in value]
    if isinstance(value, (UUID, datetime, date, Decimal)): return str(value) if isinstance(value, (UUID, Decimal)) else value.isoformat()
    if hasattr(value, "keys"): return {key: _json(value[key]) for key in value.keys()}
    return value


def _errors(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        try: return handler(*args, **kwargs)
        except TaskError as exc:
            return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=exc.status_code,
                           error=exc.__class__.__name__, message=str(exc), path=request.path), exc.status_code
    return wrapped


@task_bp.post("")
@require_auth
@_errors
def create_task(event_id: str):
    task = _service().create(event_id, request.get_json(silent=True), g.user_id)
    return jsonify(_json(task)), 201


@task_bp.get("")
@require_auth
@_errors
def list_tasks(event_id: str):
    items, total, page, size = _service().list(event_id, g.user_id, request.args.to_dict(flat=True))
    return jsonify({"items": _json(items), "total": total, "page": page, "size": size})


@task_bp.get("/<task_id>")
@require_auth
@_errors
def get_task(event_id: str, task_id: str):
    return jsonify(_json(_service().get(event_id, task_id, g.user_id)))


@task_bp.patch("/<task_id>")
@require_auth
@_errors
def update_task(event_id: str, task_id: str):
    return jsonify(_json(_service().update(event_id, task_id, request.get_json(silent=True), g.user_id)))


@task_bp.delete("/<task_id>")
@require_auth
@_errors
def delete_task(event_id: str, task_id: str):
    _service().delete(event_id, task_id, g.user_id)
    return "", 204
