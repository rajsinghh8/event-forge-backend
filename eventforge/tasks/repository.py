"""Transactional SQL persistence for event-scoped tasks."""
from __future__ import annotations

from typing import Any
from uuid import UUID


class TaskRepository:
    """All methods operate on the cursor supplied by the service.

    Keeping the cursor explicit is important: a task mutation and its audit row
    must use the same connection/transaction.
    """

    def __init__(self, database: Any) -> None:
        self.db = database

    @staticmethod
    def event(cursor: Any, event_id: UUID | str, *, for_update: bool = False) -> Any:
        cursor.execute(
            "SELECT id, owner_id FROM events WHERE id = %s" + (" FOR UPDATE" if for_update else ""),
            (event_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def get(cursor: Any, event_id: UUID | str, task_id: UUID | str, *, for_update: bool = False) -> Any:
        cursor.execute(
            "SELECT * FROM tasks WHERE event_id = %s AND id = %s" + (" FOR UPDATE" if for_update else ""),
            (event_id, task_id),
        )
        return cursor.fetchone()

    @staticmethod
    def dependency(cursor: Any, task_id: UUID | str) -> Any:
        cursor.execute("SELECT * FROM tasks WHERE id = %s", (task_id,))
        return cursor.fetchone()

    @staticmethod
    def list(cursor: Any, *, event_id: UUID | str, status: str | None, priority: str | None,
             sort: str, direction: str, limit: int, offset: int) -> tuple[list[Any], int]:
        clauses = ["event_id = %s"]
        params: list[Any] = [event_id]
        for column, value in (("status", status), ("priority", priority)):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        where = " AND ".join(clauses)
        cursor.execute(f"SELECT COUNT(*) AS total FROM tasks WHERE {where}", params)
        total_row = cursor.fetchone()
        total = total_row["total"] if isinstance(total_row, dict) else total_row[0]
        # sort/direction are chosen by service allowlists, never request SQL.
        cursor.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY {sort} {direction}, id ASC LIMIT %s OFFSET %s",
            [*params, limit, offset],
        )
        return list(cursor.fetchall()), int(total)

    @staticmethod
    def create(cursor: Any, values: dict[str, Any]) -> Any:
        columns = list(values)
        cursor.execute(
            f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({', '.join('%s' for _ in columns)}) RETURNING *",
            tuple(values[column] for column in columns),
        )
        return cursor.fetchone()

    @staticmethod
    def update(cursor: Any, task_id: UUID | str, values: dict[str, Any]) -> Any:
        cursor.execute(
            f"UPDATE tasks SET {', '.join(f'{column} = %s' for column in values)}, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING *",
            tuple(values.values()) + (task_id,),
        )
        return cursor.fetchone()

    @staticmethod
    def delete(cursor: Any, task_id: UUID | str) -> bool:
        cursor.execute("DELETE FROM tasks WHERE id = %s", (task_id,))
        return cursor.rowcount == 1

    @staticmethod
    def has_dependents(cursor: Any, task_id: UUID | str) -> bool:
        cursor.execute("SELECT id FROM tasks WHERE dependency_task_id = %s LIMIT 1", (task_id,))
        return cursor.fetchone() is not None

    @staticmethod
    def audit(cursor: Any, *, audit_id: UUID | str, event_id: Any, user_id: Any, action: str,
              task_id: Any, changes: str) -> None:
        cursor.execute(
            "INSERT INTO audit_logs (id, event_id, actor_user_id, resource_type, resource_id, action, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
            (audit_id, event_id, user_id, "task", task_id, action, changes),
        )
