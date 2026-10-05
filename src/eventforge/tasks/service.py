"""Task use cases; HTTP routes may call this service without domain leakage."""
from __future__ import annotations

from .dependencies import validate_dependency
from .lifecycle import validate_task_transition
from .models import ActivityContract, TaskDependency, TaskStatus
from .repository import ActivityPublisher, TaskRepository


class TaskNotFound(LookupError):
    pass


class TaskService:
    def __init__(self, tasks: TaskRepository, activities: ActivityPublisher) -> None:
        self._tasks = tasks
        self._activities = activities

    def change_status(self, task_id: int, status: TaskStatus, actor_id: int) -> None:
        task = self._tasks.get_task(task_id)
        if task is None:
            raise TaskNotFound(task_id)
        validate_task_transition(task.status, status)
        self._tasks.set_status(task_id, status)
        self._activities.publish_activity(ActivityContract(task.event_id, actor_id, "task.status_changed", {"task_id": task_id, "status": status.value}))

    def add_dependency(self, task_id: int, depends_on_task_id: int, actor_id: int) -> None:
        task = self._tasks.get_task(task_id)
        prerequisite = self._tasks.get_task(depends_on_task_id)
        if task is None or prerequisite is None:
            raise TaskNotFound(task_id if task is None else depends_on_task_id)
        validate_dependency(task, prerequisite, self._tasks.dependencies_of)
        self._tasks.add_dependency(TaskDependency(task_id, depends_on_task_id))
        self._activities.publish_activity(ActivityContract(task.event_id, actor_id, "task.dependency_added", {"task_id": task_id, "depends_on_task_id": depends_on_task_id}))
