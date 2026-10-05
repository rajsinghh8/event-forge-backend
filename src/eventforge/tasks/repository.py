"""Persistence ports for the task resource."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import ActivityContract, Task, TaskDependency, TaskStatus


class TaskRepository(Protocol):
    def get_task(self, task_id: int) -> Task | None: ...
    def dependencies_of(self, task_id: int) -> Iterable[int]: ...
    def set_status(self, task_id: int, status: TaskStatus) -> None: ...
    def add_dependency(self, dependency: TaskDependency) -> None: ...


class ActivityPublisher(Protocol):
    def publish_activity(self, activity: ActivityContract) -> None: ...
