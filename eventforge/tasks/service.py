"""Task business rules for the event-scoped task API."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from .repository import TaskRepository


class TaskError(Exception):
    status_code = 400
class NotFound(TaskError): status_code = 404
class Conflict(TaskError): status_code = 409
class Forbidden(TaskError): status_code = 403
class ValidationError(TaskError): status_code = 400


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
        return row.get(key) if isinstance(row, dict) else getattr(row, key, None)

    @staticmethod
    def _uuid(value: Any, field: str) -> UUID:
        try: return UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc: raise ValidationError(f"{field} must be a UUID") from exc

    @staticmethod
    def _due_at(value: Any) -> datetime | None:
        if value is None: return None
        if not isinstance(value, str): raise ValidationError("due_at must be an ISO-8601 timestamp or null")
        try: return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc: raise ValidationError("due_at must be an ISO-8601 timestamp") from exc

    def _clean(self, payload: Any, *, creating: bool) -> dict[str, Any]:
        if not isinstance(payload, dict): raise ValidationError("JSON object required")
        if creating and "title" not in payload: raise ValidationError("title is required")
        unknown = set(payload) - self.MUTABLE_FIELDS
        if unknown: raise ValidationError(f"unknown fields: {', '.join(sorted(unknown))}")
        values = {key: payload[key] for key in payload if key in self.MUTABLE_FIELDS}
        if "dependency_task_id" in values and values["dependency_task_id"] is not None:
            values["dependency_task_id"] = self._uuid(values["dependency_task_id"], "dependency_task_id")
        if "title" in values:
            if not isinstance(values["title"], str) or not values["title"].strip(): raise ValidationError("title must be a non-empty string")
            values["title"] = values["title"].strip()
            if len(values["title"]) > 255: raise ValidationError("title must be at most 255 characters")
        if "description" in values and values["description"] is not None and not isinstance(values["description"], str):
            raise ValidationError("description must be a string or null")
        if "status" in values and values["status"] not in self.STATUSES: raise ValidationError("status must be one of: todo, in_progress, completed, cancelled")
        if "priority" in values and values["priority"] not in self.PRIORITIES: raise ValidationError("priority must be one of: low, medium, high")
        if "due_at" in values: values["due_at"] = self._due_at(values["due_at"])
        if creating:
            values = {"description": None, "status": "todo", "priority": "medium", "due_at": None,
                      "dependency_task_id": None, **values}
        return values

    def _event_owner(self, cursor: Any, event_id: UUID, user_id: Any, *, lock: bool = False) -> None:
        event = self.repository.event(cursor, event_id, for_update=lock)
        if event is None: raise NotFound("event not found")
        if str(self._value(event, "owner_id")) != str(user_id): raise Forbidden("you do not own this event")

    def _task(self, cursor: Any, event_id: UUID, task_id: UUID, *, lock: bool = False) -> Any:
        task = self.repository.get(cursor, event_id, task_id, for_update=lock)
        if task is None: raise NotFound("task not found")
        return task

    def _dependency_is_valid(self, cursor: Any, task_id: UUID, event_id: UUID, dependency_id: Any) -> None:
        if dependency_id is None: return
        if task_id == dependency_id: raise ValidationError("a task cannot depend on itself")
        dependency = self.repository.dependency(cursor, dependency_id)
        if dependency is None: raise ValidationError("dependency_task_id does not reference a task")
        if str(self._value(dependency, "event_id")) != str(event_id): raise ValidationError("a dependency must belong to the same event")
        visited: set[str] = set()
        while dependency is not None:
            current_id = str(self._value(dependency, "id"))
            if current_id == str(task_id): raise ValidationError("dependency would create a cycle")
            if current_id in visited: raise ValidationError("dependency chain contains a cycle")
            visited.add(current_id)
            parent_id = self._value(dependency, "dependency_task_id")
            dependency = self.repository.dependency(cursor, parent_id) if parent_id else None

    def _assert_completion_allowed(self, cursor: Any, dependency_id: Any, status: str | None) -> None:
        if status != "completed" or dependency_id is None: return
        dependency = self.repository.dependency(cursor, dependency_id)
        if dependency is None or self._value(dependency, "status") != "completed":
            raise Conflict("dependent task must be completed first")

    def _audit(self, cursor: Any, event_id: UUID, user_id: Any, action: str, task_id: UUID, changes: dict[str, Any]) -> None:
        self.repository.audit(cursor, audit_id=uuid4(), event_id=event_id, user_id=user_id, action=action,
                              task_id=task_id, changes=json.dumps(changes, default=str))

    def create(self, event_id: str, payload: Any, user_id: Any) -> Any:
        event_uuid, values = self._uuid(event_id, "event_id"), self._clean(payload, creating=True)
        with self.db.transaction() as connection:
            with connection.cursor() as cursor:
                self._event_owner(cursor, event_uuid, user_id, lock=True)
                task_id = uuid4()
                self._dependency_is_valid(cursor, task_id, event_uuid, values["dependency_task_id"])
                self._assert_completion_allowed(cursor, values["dependency_task_id"], values["status"])
                task = self.repository.create(cursor, {"id": task_id, "event_id": event_uuid, **values})
                self._audit(cursor, event_uuid, user_id, "create", task_id, values)
                return task

    def get(self, event_id: str, task_id: str, user_id: Any) -> Any:
        event_uuid, task_uuid = self._uuid(event_id, "event_id"), self._uuid(task_id, "task_id")
        with self.db.cursor() as cursor:
            self._event_owner(cursor, event_uuid, user_id)
            return self._task(cursor, event_uuid, task_uuid)

    def list(self, event_id: str, user_id: Any, query: dict[str, Any]) -> tuple[list[Any], int, int, int]:
        def positive(name: str, default: int, maximum: int) -> int:
            try: value = int(query.get(name, default))
            except (TypeError, ValueError) as exc: raise ValidationError(f"{name} must be an integer") from exc
            if not 1 <= value <= maximum: raise ValidationError(f"{name} must be between 1 and {maximum}")
            return value
        page, size = positive("page", 1, 1_000_000), positive("size", 20, 100)
        status, priority = query.get("status"), query.get("priority")
        if status is not None and status not in self.STATUSES: raise ValidationError("invalid status filter")
        if priority is not None and priority not in self.PRIORITIES: raise ValidationError("invalid priority filter")
        sort, direction = query.get("sort", "created_at"), str(query.get("order", "desc")).lower()
        if sort not in self.SORT_FIELDS: raise ValidationError("invalid sort field")
        if direction not in {"asc", "desc"}: raise ValidationError("order must be asc or desc")
        event_uuid = self._uuid(event_id, "event_id")
        with self.db.cursor() as cursor:
            self._event_owner(cursor, event_uuid, user_id)
            items, total = self.repository.list(cursor, event_id=event_uuid, status=status, priority=priority,
                                                sort=sort, direction=direction.upper(), limit=size, offset=(page - 1) * size)
        return items, total, page, size

    def update(self, event_id: str, task_id: str, payload: Any, user_id: Any) -> Any:
        event_uuid, task_uuid, values = self._uuid(event_id, "event_id"), self._uuid(task_id, "task_id"), self._clean(payload, creating=False)
        if not values: raise ValidationError("at least one mutable field is required")
        with self.db.transaction() as connection:
            with connection.cursor() as cursor:
                self._event_owner(cursor, event_uuid, user_id, lock=True)
                task = self._task(cursor, event_uuid, task_uuid, lock=True)
                dependency_id = values.get("dependency_task_id", self._value(task, "dependency_task_id"))
                self._dependency_is_valid(cursor, task_uuid, event_uuid, dependency_id)
                self._assert_completion_allowed(cursor, dependency_id, values.get("status"))
                updated = self.repository.update(cursor, task_uuid, values)
                action = "status_change" if "status" in values and values["status"] != self._value(task, "status") else "update"
                self._audit(cursor, event_uuid, user_id, action, task_uuid, values)
                return updated

    def delete(self, event_id: str, task_id: str, user_id: Any) -> None:
        event_uuid, task_uuid = self._uuid(event_id, "event_id"), self._uuid(task_id, "task_id")
        with self.db.transaction() as connection:
            with connection.cursor() as cursor:
                self._event_owner(cursor, event_uuid, user_id, lock=True)
                self._task(cursor, event_uuid, task_uuid, lock=True)
                if self.repository.has_dependents(cursor, task_uuid): raise Conflict("task cannot be deleted while other tasks depend on it")
                self.repository.delete(cursor, task_uuid)
                self._audit(cursor, event_uuid, user_id, "delete", task_uuid, {"event_id": str(event_uuid)})
