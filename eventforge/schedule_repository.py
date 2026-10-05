"""Direct PostgreSQL persistence for event schedule items.

The repository deliberately accepts a cursor for writes so the service can keep
item mutation and its audit record in one Database.transaction() call.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID


SCHEDULE_COLUMNS = """
    id, event_id, name, description, start_at, end_at, created_at, updated_at
"""


class ScheduleRepository:
    """Parameterized queries for the ``schedule_items`` table."""

    def __init__(self, database: Any) -> None:
        self._database = database

    @staticmethod
    def _one(cursor: Any) -> Mapping[str, Any] | None:
        return cursor.fetchone()

    def event_owner(self, cursor: Any, event_id: UUID) -> Mapping[str, Any] | None:
        cursor.execute("SELECT id, owner_id FROM events WHERE id = %s", (event_id,))
        return self._one(cursor)

    def get(self, cursor: Any, event_id: UUID, item_id: UUID, *, for_update: bool = False) -> Mapping[str, Any] | None:
        lock = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT {SCHEDULE_COLUMNS} FROM schedule_items WHERE event_id = %s AND id = %s{lock}",
            (event_id, item_id),
        )
        return self._one(cursor)

    def find_overlap(
        self, cursor: Any, event_id: UUID, start_at: Any, end_at: Any, *, exclude_id: UUID | None = None
    ) -> Mapping[str, Any] | None:
        sql = """
            SELECT id, name, start_at, end_at
            FROM schedule_items
            WHERE event_id = %s
              AND start_at < %s
              AND end_at > %s
        """
        params: list[Any] = [event_id, end_at, start_at]
        if exclude_id is not None:
            sql += " AND id <> %s"
            params.append(exclude_id)
        sql += " LIMIT 1"
        cursor.execute(sql, params)
        return self._one(cursor)

    def insert(self, cursor: Any, values: Mapping[str, Any]) -> Mapping[str, Any]:
        cursor.execute(
            f"""
            INSERT INTO schedule_items
                (id, event_id, name, description, start_at, end_at, created_at, updated_at)
            VALUES
                (%(id)s, %(event_id)s, %(name)s, %(description)s, %(start_at)s, %(end_at)s,
                 CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING {SCHEDULE_COLUMNS}
            """,
            values,
        )
        row = self._one(cursor)
        assert row is not None
        return row

    def update(self, cursor: Any, item_id: UUID, values: Mapping[str, Any]) -> Mapping[str, Any]:
        cursor.execute(
            f"""
            UPDATE schedule_items
            SET name = %(name)s, description = %(description)s,
                start_at = %(start_at)s, end_at = %(end_at)s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %(id)s
            RETURNING {SCHEDULE_COLUMNS}
            """,
            {**values, "id": item_id},
        )
        row = self._one(cursor)
        assert row is not None
        return row

    def delete(self, cursor: Any, event_id: UUID, item_id: UUID) -> bool:
        cursor.execute("DELETE FROM schedule_items WHERE event_id = %s AND id = %s", (event_id, item_id))
        return cursor.rowcount == 1

    def list(
        self,
        cursor: Any,
        event_id: UUID,
        *,
        page: int,
        size: int,
        sort_sql: str,
        text: str | None,
        name: str | None,
        start_date: Any | None,
        end_date: Any | None,
    ) -> tuple[list[Mapping[str, Any]], int]:
        clauses = ["event_id = %s"]
        params: list[Any] = [event_id]
        if text:
            clauses.append("(name ILIKE %s OR COALESCE(description, '') ILIKE %s)")
            like = f"%{text}%"
            params.extend((like, like))
        if name:
            clauses.append("name ILIKE %s")
            params.append(f"%{name}%")
        # Date filters select intervals that begin in the requested date range.
        if start_date:
            clauses.append("start_at >= %s")
            params.append(start_date)
        if end_date:
            clauses.append("start_at < (%s::date + INTERVAL '1 day')")
            params.append(end_date)
        where = " AND ".join(clauses)
        cursor.execute(f"SELECT COUNT(*) AS total FROM schedule_items WHERE {where}", params)
        total_row = self._one(cursor)
        total = int(total_row["total"] if total_row else 0)
        cursor.execute(
            f"SELECT {SCHEDULE_COLUMNS} FROM schedule_items WHERE {where} "
            f"ORDER BY {sort_sql} LIMIT %s OFFSET %s",
            [*params, size, (page - 1) * size],
        )
        return list(cursor.fetchall()), total

    def insert_audit(
        self,
        cursor: Any,
        *,
        audit_id: UUID,
        event_id: UUID,
        actor_user_id: UUID,
        resource_id: UUID,
        action: str,
        details_json: str,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO audit_logs
                (id, event_id, actor_user_id, resource_type, resource_id, action, details, created_at)
            VALUES (%s, %s, %s, 'schedule_item', %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
            """,
            (audit_id, event_id, actor_user_id, resource_id, action, details_json),
        )
