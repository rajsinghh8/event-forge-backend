"""Core EventForge event, task, and guest resource service.

This module deliberately operates on mapping DTOs.  Repository implementations
may persist them however they choose, but must never leak persistence models
through this service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import ContextManager, Protocol, TypeAlias
from contextlib import nullcontext
from functools import wraps
from datetime import date, datetime


def _transactional(method):
    """Keep persistence, audit, and notification writes in one unit of work."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        transaction = getattr(self._repository, "transaction", None)
        with transaction() if callable(transaction) else nullcontext():
            return method(self, *args, **kwargs)
    return wrapped


def _mutation(method):
    return _transactional(method)

from eventforge import errors


DTOValue: TypeAlias = str | int | float | bool | Decimal | None | dict[str, "DTOValue"] | list["DTOValue"]
DTO: TypeAlias = dict[str, DTOValue]


class CoreRepository(Protocol):
    """Repository contract required by :class:`CoreResourceService`.

    Every resource lookup/mutation receives ``user_id``.  Implementations must
    apply that owner scope and raise ``errors.NotFoundError`` for resources
    outside it, so their existence is not disclosed.
    """

    def create_event(self, user_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def get_event(self, user_id: str, event_id: str) -> Mapping[str, object]: ...
    def list_events(self, user_id: str, *, limit: int, offset: int) -> tuple[Sequence[Mapping[str, object]], int]: ...
    def update_event(self, user_id: str, event_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def delete_event(self, user_id: str, event_id: str) -> None: ...

    def create_task(self, user_id: str, event_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def get_task(self, user_id: str, event_id: str, task_id: str) -> Mapping[str, object]: ...
    def list_tasks(self, user_id: str, event_id: str) -> Sequence[Mapping[str, object]]: ...
    def update_task(self, user_id: str, event_id: str, task_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def delete_task(self, user_id: str, event_id: str, task_id: str) -> None: ...
    def list_task_dependents(self, user_id: str, event_id: str, task_id: str) -> Sequence[Mapping[str, object]]: ...

    def create_guest(self, user_id: str, event_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def get_guest(self, user_id: str, event_id: str, guest_id: str) -> Mapping[str, object]: ...
    def list_guests(self, user_id: str, event_id: str, *, limit: int, offset: int) -> tuple[Sequence[Mapping[str, object]], int]: ...
    def update_guest(self, user_id: str, event_id: str, guest_id: str, values: Mapping[str, object]) -> Mapping[str, object]: ...
    def delete_guest(self, user_id: str, event_id: str, guest_id: str) -> None: ...
    def count_accepted_guests(self, user_id: str, event_id: str) -> int: ...

    def audit(self, user_id: str, action: str, resource: str, resource_id: str, details: Mapping[str, object]) -> None: ...
    def notify(self, user_id: str, kind: str, details: Mapping[str, object]) -> None: ...


class CoreResourceService:
    """Owner-scoped business operations for events, tasks, and guests.

    ``guest_capacity`` (or the backwards-compatible ``capacity`` event field)
    is the maximum number of guests whose RSVP ``status`` is ``"accepted"``.
    Task statuses are ``pending``, ``in_progress``, ``blocked``, ``completed``,
    and ``cancelled``; completed and cancelled tasks are terminal.
    """

    _TASK_TRANSITIONS = {
        "pending": frozenset({"in_progress", "cancelled"}),
        "in_progress": frozenset({"blocked", "completed", "cancelled"}),
        "blocked": frozenset({"pending", "in_progress", "cancelled"}),
        "completed": frozenset(),
        "cancelled": frozenset(),
    }

    def __init__(self, repository: CoreRepository) -> None:
        self._repository = repository

    # Events
    @_mutation
    def create_event(self, user_id: str, values: Mapping[str, object]) -> DTO:
        payload = dict(values)
        event = self._repository.create_event(user_id, payload)
        result = _dto(event)
        self._record(user_id, "create", "event", _id(result), result)
        return result

    def get_event(self, user_id: str, event_id: str) -> DTO:
        # Detail DTOs expose the live RSVP aggregate, not a stale denormalized value.
        result = _dto(self._repository.get_event(user_id, event_id))
        result["accepted_guest_count"] = self._repository.count_accepted_guests(user_id, event_id)
        return result

    def list_events(self, user_id: str, *, limit: int = 20, offset: int = 0, filters: Mapping[str, object] | None = None, sort: str = "-id") -> DTO:
        _pagination(limit, offset)
        items, total = self._repository.list_events(user_id, limit=limit, offset=offset, filters=dict(filters or {}), sort=sort)
        return {"items": [_dto(item) for item in items], "total": total, "limit": limit, "offset": offset}

    @_mutation
    def update_event(self, user_id: str, event_id: str, values: Mapping[str, object]) -> DTO:
        result = _dto(self._repository.update_event(user_id, event_id, dict(values)))
        self._record(user_id, "update", "event", event_id, result)
        return result

    @_mutation
    def delete_event(self, user_id: str, event_id: str) -> None:
        self._repository.get_event(user_id, event_id)
        self._repository.delete_event(user_id, event_id)
        self._record(user_id, "delete", "event", event_id, {"id": event_id})

    # Tasks
    @_mutation
    def create_task(self, user_id: str, event_id: str, values: Mapping[str, object]) -> DTO:
        self._repository.get_event(user_id, event_id)
        payload = dict(values)
        title = payload.get("title")
        priority = payload.get("priority")
        if not isinstance(title, str) or not title.strip():
            raise errors.ValidationError("title is required")
        if not isinstance(priority, str) or priority not in {"low", "medium", "high"}:
            raise errors.ValidationError("priority must be one of low, medium, high")
        payload["title"] = title.strip()
        dependencies = self._dependencies(payload)
        self._validate_dependencies(user_id, event_id, dependencies)
        status = payload.setdefault("status", "pending")
        if status != "pending":
            raise errors.ValidationError("new tasks must start with status 'pending'")
        result = _dto(self._repository.create_task(user_id, event_id, payload))
        self._record(user_id, "create", "task", _id(result), result)
        return result

    def get_task(self, user_id: str, event_id: str, task_id: str) -> DTO:
        return _dto(self._repository.get_task(user_id, event_id, task_id))

    def list_tasks(self, user_id: str, event_id: str) -> list[DTO]:
        self._repository.get_event(user_id, event_id)
        return [_dto(task) for task in self._repository.list_tasks(user_id, event_id)]

    @_mutation
    def update_task(self, user_id: str, event_id: str, task_id: str, values: Mapping[str, object]) -> DTO:
        current = _dto(self._repository.get_task(user_id, event_id, task_id))
        payload = dict(values)
        if "status" in payload:
            self._validate_transition(current.get("status"), payload["status"])
        if "dependency_ids" in payload:
            dependencies = self._dependencies(payload)
            if task_id in dependencies:
                raise errors.ValidationError("a task cannot depend on itself")
            self._validate_dependencies(user_id, event_id, dependencies)
            self._ensure_acyclic(user_id, event_id, task_id, dependencies)
        result = _dto(self._repository.update_task(user_id, event_id, task_id, payload))
        self._record(user_id, "status_change" if "status" in payload else "update", "task", task_id, result)
        return result

    @_mutation
    def delete_task(self, user_id: str, event_id: str, task_id: str) -> None:
        self._repository.get_task(user_id, event_id, task_id)
        if self._repository.list_task_dependents(user_id, event_id, task_id):
            raise errors.ConflictError("task cannot be deleted while another task depends on it")
        self._repository.delete_task(user_id, event_id, task_id)
        self._record(user_id, "delete", "task", task_id, {"id": task_id, "event_id": event_id})

    # Guests
    @_mutation
    def create_guest(self, user_id: str, event_id: str, values: Mapping[str, object]) -> DTO:
        event = _dto(self._repository.get_event(user_id, event_id))
        payload = dict(values)
        if payload.get("status") == "accepted":
            self._ensure_capacity(user_id, event_id, event)
        result = _dto(self._repository.create_guest(user_id, event_id, payload))
        self._record(user_id, "create", "guest", _id(result), result)
        return result

    def get_guest(self, user_id: str, event_id: str, guest_id: str) -> DTO:
        return _dto(self._repository.get_guest(user_id, event_id, guest_id))

    def list_guests(self, user_id: str, event_id: str, *, limit: int = 20, offset: int = 0) -> DTO:
        _pagination(limit, offset)
        self._repository.get_event(user_id, event_id)
        items, total = self._repository.list_guests(user_id, event_id, limit=limit, offset=offset)
        return {"items": [_dto(item) for item in items], "total": total, "limit": limit, "offset": offset}

    @_mutation
    def update_guest(self, user_id: str, event_id: str, guest_id: str, values: Mapping[str, object]) -> DTO:
        event = _dto(self._repository.get_event(user_id, event_id))
        current = _dto(self._repository.get_guest(user_id, event_id, guest_id))
        payload = dict(values)
        if payload.get("status") == "accepted" and current.get("status") != "accepted":
            self._ensure_capacity(user_id, event_id, event)
        result = _dto(self._repository.update_guest(user_id, event_id, guest_id, payload))
        self._record(user_id, "status_change" if "status" in payload else "update", "guest", guest_id, result)
        return result

    @_mutation
    def delete_guest(self, user_id: str, event_id: str, guest_id: str) -> None:
        self._repository.get_guest(user_id, event_id, guest_id)
        self._repository.delete_guest(user_id, event_id, guest_id)
        self._record(user_id, "delete", "guest", guest_id, {"id": guest_id, "event_id": event_id})

    def _record(self, user_id: str, action: str, resource: str, resource_id: str, details: Mapping[str, object]) -> None:
        safe = _dto(details)
        self._repository.audit(user_id, action, resource, resource_id, safe)
        self._repository.notify(user_id, action, safe)

    def _dependencies(self, values: Mapping[str, object]) -> list[str]:
        raw = values.get("dependency_ids", [])
        if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
            raise errors.ValidationError("dependency_ids must be a list of non-empty task ids")
        if len(set(raw)) != len(raw):
            raise errors.ValidationError("dependency_ids must not contain duplicates")
        return raw

    def _validate_dependencies(self, user_id: str, event_id: str, dependency_ids: Sequence[str]) -> None:
        # Scoped lookup establishes that every dependency belongs to this event.
        for dependency_id in dependency_ids:
            self._repository.get_task(user_id, event_id, dependency_id)

    def _ensure_acyclic(self, user_id: str, event_id: str, task_id: str, dependency_ids: Sequence[str]) -> None:
        graph = {_id(_dto(task)): set(_dependency_values(task)) for task in self._repository.list_tasks(user_id, event_id)}
        graph[task_id] = set(dependency_ids)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> None:
            if node in visiting:
                raise errors.ConflictError("task dependency would create a cycle")
            if node in visited:
                return
            visiting.add(node)
            for dependency in graph.get(node, set()):
                visit(dependency)
            visiting.remove(node)
            visited.add(node)

        visit(task_id)

    def _validate_transition(self, old: object, new: object) -> None:
        if old == new:
            return
        if not isinstance(old, str) or not isinstance(new, str) or new not in self._TASK_TRANSITIONS.get(old, frozenset()):
            raise errors.ValidationError(f"illegal task status transition: {old!r} -> {new!r}")

    def _ensure_capacity(self, user_id: str, event_id: str, event: Mapping[str, object]) -> None:
        capacity = event.get("guest_capacity", event.get("capacity"))
        if capacity is None:
            return
        if isinstance(capacity, bool):
            raise errors.ValidationError("guest capacity must be a non-negative integer")
        try:
            maximum = int(capacity)  # Decimal-safe and accepts repository Decimal values.
            is_integral = Decimal(str(maximum)) == Decimal(str(capacity))
        except (TypeError, ValueError, InvalidOperation):
            raise errors.ValidationError("guest capacity must be a non-negative integer")
        if maximum < 0 or not is_integral:
            raise errors.ValidationError("guest capacity must be a non-negative integer")
        if self._repository.count_accepted_guests(user_id, event_id) >= maximum:
            raise errors.ConflictError("event guest capacity has been reached")


def _pagination(limit: int, offset: int) -> None:
    if (not isinstance(limit, int) or not isinstance(offset, int) or isinstance(limit, bool)
            or isinstance(offset, bool) or limit < 1 or offset < 0):
        raise errors.ValidationError("limit must be positive and offset must be non-negative")


def _id(values: Mapping[str, object]) -> str:
    value = values.get("id")
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if not isinstance(value, str) or not value:
        raise errors.ValidationError("repository returned a resource without an id")
    return value


def _dependency_values(values: Mapping[str, object]) -> list[str]:
    raw = values.get("dependency_ids", [])
    return [item for item in raw if isinstance(item, str)] if isinstance(raw, list) else []


def _dto(value: Mapping[str, object]) -> DTO:
    """Copy a repository mapping into a JSON/Decimal-safe DTO dictionary."""
    return {str(key): _dto_value(item) for key, item in value.items()}


def _dto_value(value: object) -> DTOValue:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return _dto(value)
    if isinstance(value, (list, tuple)):
        return [_dto_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    # Repository DTOs must contain JSON-like scalars; avoid exposing models.
    raise errors.ValidationError("repository returned a non-DTO value")
