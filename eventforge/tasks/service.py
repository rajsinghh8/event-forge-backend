"""Task business rules and audit-aware command handling."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .repository import TaskRepository


class TaskError(Exception):
    status_code = 400


class NotFound(TaskError):
    status_code = 404


class Conflict(TaskError):
    status_code = 409


class Forbidden(TaskError):
    status_code = 403


class ValidationError(TaskError):
    status_code = 400


class TaskService:
    STATUSES = {"todo", "in_progress", "completed", "cancelled"}
    PRIORITIES = {"low", "medium", "high"}
    SORT_FIELDS = {"created_at", "updated_at", "title", "due_at", "priority", "status"}
    MUTABLE_FIELDS = {"title", "description", "status", "priority", "due_at", "dependency_task_id"}

    def __init__(self, database: Any, repository: TaskRepository | None = None) -> None:
        self.db = database
        self.repository = repository or TaskRepository(database)

    @staticmethod
    def _value(row: Any, key: str) -> Any:
        if isinstance(row, dict):
            return row.get(key)
        # Database implementations in this application use dict rows; this makes
        # service tests using simple object rows equally usable.
        return getattr(row, key, None)

    @staticmethod
    def _uuid(value: Any, field: str) -> UUID:
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValidationError(f"{field} must be a UUID") from exc

    @staticmethod
    def _due_at(value: Any) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValidationError("due_at must be an ISO-8601 timestamp or null")
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError("due_at must be an ISO-8601 timestamp") from exc

    def _clean(self, payload: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValidationError("JSON object required")
        if creating:
            missing = [field for field in ("event_id", "title") if field not in payload]
            if missing:
                raise ValidationError(f"{missing[0]} is required")
        unknown = set(payload) - (self.MUTABLE_FIELDS | {"event_id"})
        if unknown:
            raise ValidationError(f"unknown fields: {', '.join(sorted(unknown))}")
        if not creating and "event_id" in payload:
            raise ValidationError("event_id cannot be changed")
        values = {key: payload[key] for key in payload if key in self.MUTABLE_FIELDS or (creating and key == "event_id")}
        if "event_id" in values:
            values["event_id"] = self._uuid(values["event_id"], "event_id")
        if "dependency_task_id" in values and values["dependency_task_id"] is not None:
            values["dependency_task_id"] = self._uuid(values["dependency_task_id"], "dependency_task_id")
        if "title" in values:
            title = values["title"]
            if not isinstance(title, str) or not (title := title.strip()):
                raise ValidationError("title must be a non-empty string")
            if len(title) > 255:
                raise ValidationError("title must be at most 255 characters")
            values["title"] = title
        if "description" in values and values["description"] is not None and not isinstance(values["description"], str):
            raise ValidationError("description must be a string or null")
        if "status" in values and values["status"] not in self.STATUSES:
            raise ValidationError("status must be one of: todo, in_progress, completed, cancelled")
        if "priority" in values and values["priority"] not in self.PRIORITIES:
            raise ValidationError("priority must be one of: low, medium, high")
        if "due_at" in values:
            values["due_at"] = self._due_at(values["due_at"])
        if creating:
            values.setdefault("description", None)
            values.setdefault("status", "todo")
            values.setdefault("priority", "medium")
            values.setdefault("due_at", None)
            values.setdefault("dependency_task_id", None)
        return values

    def _dependency_is_valid(self, task_id: Any, event_id: Any, dependency_id: Any) -> None:
        if dependency_id is None:
            return
        if str(task_id) == str(dependency_id):
            raise ValidationError("a task cannot depend on itself")
        dependency = self.repository.get(dependency_id)
        if dependency is None:
            raise ValidationError("dependency_task_id does not reference a task")
        if str(self._value(dependency, "event_id")) != str(event_id):
            raise ValidationError("a dependency must belong to the same event")
        # Follow the chain to prevent indirect cycles.  The visited set also
        # protects against a pre-existing corrupt cycle.
        visited: set[str] = set()
        cursor = dependency
        while cursor is not None:
            cursor_id = str(self._value(cursor, "id"))
            if cursor_id == str(task_id):
                raise ValidationError("dependency would create a cycle")
            if cursor_id in visited:
                raise ValidationError("dependency chain contains a cycle")
            visited.add(cursor_id)
            parent_id = self._value(cursor, "dependency_task_id")
            cursor = self.repository.get(parent_id) if parent_id else None

    def _assert_completion_allowed(self, event_id: Any, dependency_id: Any, new_status: str | None) -> None:
        if new_status != "completed" or dependency_id is None:
            return
        dependency = self.repository.get(dependency_id)
        if dependency is None or self._value(dependency, "status") != "completed":
            raise Conflict("dependent task must be completed first")

    def assert_event_owner(self, event_id: str, user_id: Any) -> None:
        event_uuid = self._uuid(event_id, "event_id")
        owner = self.repository.event_owner(event_uuid)
        if owner is None:
            raise NotFound("event not found")
        if str(self._value(owner, "owner_id")) != str(user_id):
            raise Forbidden("you do not own this event")

    def _audit(self, event_id: Any, user_id: Any, action: str, task_id: Any, changes: dict[str, Any]) -> None:
        self.repository.audit(
            audit_id=uuid4(), event_id=event_id, user_id=user_id, action=action, task_id=task_id,
            changes=json.dumps(changes, default=str),
        )

    def create(self, payload: dict[str, Any], user_id: Any) -> Any:
        values = self._clean(payload, creating=True)
        with self.db.transaction():
            if not self.repository.event_exists(values["event_id"]):
                raise NotFound("event not found")
            task_id = uuid4()
            self._dependency_is_valid(task_id, values["event_id"], values["dependency_task_id"])
            self._assert_completion_allowed(values["event_id"], values["dependency_task_id"], values["status"])
            task = self.repository.create({"id": task_id, **values})
            self._audit(values["event_id"], user_id, "created", task_id, values)
            return task

    def get(self, task_id: str) -> Any:
        task = self.repository.get(self._uuid(task_id, "task_id"))
        if task is None:
            raise NotFound("task not found")
        return task

    def list(self, query: dict[str, Any]) -> tuple[list[Any], int, int, int]:
        def positive(name: str, default: int, maximum: int) -> int:
            raw = query.get(name, default)
            try:
                value = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{name} must be an integer") from exc
            if not 1 <= value <= maximum:
                raise ValidationError(f"{name} must be between 1 and {maximum}")
            return value
        page, size = positive("page", 1, 1_000_000), positive("size", 20, 100)
        status, priority = query.get("status"), query.get("priority")
        if status is not None and status not in self.STATUSES:
            raise ValidationError("invalid status filter")
        if priority is not None and priority not in self.PRIORITIES:
            raise ValidationError("invalid priority filter")
        sort = query.get("sort", "created_at")
        if sort not in self.SORT_FIELDS:
            raise ValidationError("invalid sort field")
        direction = str(query.get("order", "desc")).lower()
        if direction not in {"asc", "desc"}:
            raise ValidationError("order must be asc or desc")
        event_id = query.get("event_id")
        if event_id is not None:
            event_id = str(self._uuid(event_id, "event_id"))
        items, total = self.repository.list(event_id=event_id, status=status, priority=priority,
                                            sort=sort, direction=direction.upper(), limit=size, offset=(page - 1) * size)
        return items, total, page, size

    def update(self, task_id: str, payload: dict[str, Any], user_id: Any) -> Any:
        task = self.get(task_id)
        values = self._clean(payload, creating=False)
        if not values:
            raise ValidationError("at least one mutable field is required")
        task_uuid = self._uuid(task_id, "task_id")
        with self.db.transaction():
            event_id = self._value(task, "event_id")
            dependency_id = values.get("dependency_task_id", self._value(task, "dependency_task_id"))
            self._dependency_is_valid(task_uuid, event_id, dependency_id)
            self._assert_completion_allowed(event_id, dependency_id, values.get("status"))
            updated = self.repository.update(task_uuid, values)
            self._audit(event_id, user_id, "updated", task_uuid, values)
            return updated

    def delete(self, task_id: str, user_id: Any) -> None:
        task = self.get(task_id)
        task_uuid = self._uuid(task_id, "task_id")
        with self.db.transaction():
            if self.repository.has_dependents(task_uuid):
                raise Conflict("task cannot be deleted while other tasks depend on it")
            self.repository.delete(task_uuid)
            self._audit(self._value(task, "event_id"), user_id, "deleted", task_uuid, {"event_id": str(self._value(task, "event_id"))})
