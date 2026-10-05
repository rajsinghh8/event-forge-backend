"""Oracle implementation fragments for task persistence (all values are named binds)."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import Task, TaskDependency, TaskStatus


class OracleTaskRepository:
    """Adapter for a python-oracledb connection; transaction ownership stays with caller."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def get_task(self, task_id: int) -> Task | None:
        sql = """SELECT id, event_id, title, status, due_at, assignee_id
                 FROM tasks WHERE id = :task_id"""
        with self._connection.cursor() as cursor:
            cursor.execute(sql, task_id=task_id)
            row = cursor.fetchone()
        if row is None:
            return None
        return Task(row[0], row[1], row[2], TaskStatus(row[3]), row[4], row[5])

    def dependencies_of(self, task_id: int) -> Iterable[int]:
        sql = "SELECT depends_on_task_id FROM task_dependencies WHERE task_id = :task_id"
        with self._connection.cursor() as cursor:
            cursor.execute(sql, task_id=task_id)
            return tuple(row[0] for row in cursor)

    def set_status(self, task_id: int, status: TaskStatus) -> None:
        sql = "UPDATE tasks SET status = :status, updated_at = SYSTIMESTAMP WHERE id = :task_id"
        with self._connection.cursor() as cursor:
            cursor.execute(sql, status=status.value, task_id=task_id)
            if cursor.rowcount != 1:
                raise LookupError(task_id)

    def add_dependency(self, dependency: TaskDependency) -> None:
        sql = """INSERT INTO task_dependencies (task_id, depends_on_task_id)
                 VALUES (:task_id, :depends_on_task_id)"""
        with self._connection.cursor() as cursor:
            cursor.execute(sql, task_id=dependency.task_id, depends_on_task_id=dependency.depends_on_task_id)
