"""Task domain values. Persistence keeps enum values as Oracle VARCHAR2 values."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class Task:
    id: int
    event_id: int
    title: str
    status: TaskStatus
    due_at: datetime | None = None
    assignee_id: int | None = None


@dataclass(frozen=True, slots=True)
class TaskDependency:
    """`task_id` cannot begin until `depends_on_task_id` is complete."""

    task_id: int
    depends_on_task_id: int


@dataclass(frozen=True, slots=True)
class ActivityContract:
    event_id: int
    actor_id: int | None
    activity_type: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class NotificationContract:
    recipient_id: int
    notification_type: str
    payload: dict[str, Any]
