"""Pure task status transition policy."""
from __future__ import annotations

from .models import TaskStatus


class InvalidTaskTransition(ValueError):
    """Raised when a task status transition is not part of the lifecycle."""


_ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.TODO, TaskStatus.BLOCKED, TaskStatus.COMPLETED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.TODO, TaskStatus.IN_PROGRESS}),
    TaskStatus.COMPLETED: frozenset(),
}


def validate_task_transition(current: TaskStatus, requested: TaskStatus) -> None:
    """Validate a non-idempotent transition; COMPLETED is terminal."""
    if requested == current or requested not in _ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransition(f"task cannot transition from {current} to {requested}")
