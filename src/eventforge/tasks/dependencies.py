"""Task dependency validation, intentionally independent from database implementation."""
from __future__ import annotations

from collections.abc import Callable, Iterable

from .models import Task, TaskStatus


class InvalidTaskDependency(ValueError):
    pass


def validate_dependency(
    task: Task,
    prerequisite: Task,
    dependencies_of: Callable[[int], Iterable[int]],
) -> None:
    """Require same event, reject completed prerequisites, self-links and all cycles.

    `dependencies_of(id)` returns the direct prerequisite IDs of `id`.  Adding
    task -> prerequisite would cycle precisely when task is reachable from the
    prerequisite through existing prerequisite links.
    """
    if task.event_id != prerequisite.event_id:
        raise InvalidTaskDependency("tasks in a dependency must belong to the same event")
    if task.id == prerequisite.id:
        raise InvalidTaskDependency("a task cannot depend on itself")
    if prerequisite.status is TaskStatus.COMPLETED:
        raise InvalidTaskDependency("a completed task cannot be added as a dependency")

    pending = [prerequisite.id]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current == task.id:
            raise InvalidTaskDependency("task dependency would create a cycle")
        if current in visited:
            continue
        visited.add(current)
        pending.extend(dependencies_of(current))
