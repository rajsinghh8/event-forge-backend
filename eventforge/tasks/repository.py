"""SQL persistence for event tasks.

The repository deliberately contains no request or Flask concerns.  It receives the
application Database abstraction, whose methods are backed by psycopg.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID


class TaskRepository:
    def __init__(self, database: Any) -> None:
        self.db = database

    def get(self, task_id: UUID | str) -> Any:
        return self.db.fetchone("SELECT * FROM tasks WHERE id = %s", (task_id,))

    def event_exists(self, event_id: UUID | str) -> bool:
        return self.db.fetchone("SELECT id FROM events WHERE id = %s", (event_id,)) is not None

    def list(
        self,
        *,
        event_id: str | None = None,
        status: str | None = None,
        priority: str | None = None,
        sort: str = "created_at",
        direction: str = "desc",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("event_id", event_id), ("status", status), ("priority", priority)):
            if value is not None:
                clauses.append(f"{column} = %s")
                params.append(value)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        total_row = self.db.fetchone(f"SELECT COUNT(*) AS total FROM tasks{where}", tuple(params))
        total = total_row["total"] if isinstance(total_row, dict) else total_row[0]
        # sort and direction are selected by the service from fixed allowlists.
        rows = self.db.fetchall(
            f"SELECT * FROM tasks{where} ORDER BY {sort} {direction}, id ASC LIMIT %s OFFSET %s",
            tuple(params + [limit, offset]),
        )
        return list(rows), int(total)

    def create(self, values: dict[str, Any]) -> Any:
        columns = list(values)
        placeholders = ", ".join("%s" for _ in columns)
        return self.db.fetchone(
            f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders}) RETURNING *",
            tuple(values[column] for column in columns),
        )

    def update(self, task_id: UUID | str, values: dict[str, Any]) -> Any:
        assignments = ", ".join(f"{column} = %s" for column in values)
        return self.db.fetchone(
            f"UPDATE tasks SET {assignments}, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = %s RETURNING *",
            tuple(values.values()) + (task_id,),
        )

    def delete(self, task_id: UUID | str) -> bool:
        row = self.db.fetchone("DELETE FROM tasks WHERE id = %s RETURNING id", (task_id,))
        return row is not None

    def has_dependents(self, task_id: UUID | str) -> bool:
        return self.db.fetchone(
            "SELECT id FROM tasks WHERE dependency_task_id = %s LIMIT 1", (task_id,)
        ) is not None

    def audit(self, *, audit_id: UUID | str, event_id: Any, user_id: Any, action: str, task_id: Any, changes: str) -> None:
        """Record a task mutation in the shared audit trail within the caller transaction."""
        self.db.execute(
            "INSERT INTO audit_logs (id, event_id, actor_user_id, resource_type, resource_id, action, details) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
            (audit_id, event_id, user_id, "task", task_id, action, changes),
        )

    def event_owner(self, event_id: UUID | str) -> Any:
        return self.db.fetchone("SELECT owner_id FROM events WHERE id = %s", (event_id,))
