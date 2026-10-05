"""PostgreSQL data access for event guests.

All values are passed as psycopg parameters.  The only interpolated list values are
selected from ``SORT_COLUMNS`` in the service layer.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection


class GuestRepository:
    """Repository whose callers provide the current transaction connection."""

    def event_owner(self, conn: Connection[Any], event_id: UUID) -> UUID | None:
        with conn.cursor() as cur:
            cur.execute("SELECT owner_id FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
        return row[0] if row else None

    def get(self, conn: Connection[Any], event_id: UUID, guest_id: UUID, *, lock: bool = False) -> Mapping[str, Any] | None:
        suffix = " FOR UPDATE" if lock else ""
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, event_id, name, email, status, created_at, updated_at "
                "FROM guests WHERE id = %s AND event_id = %s" + suffix,
                (guest_id, event_id),
            )
            return cur.fetchone()

    def list(self, conn: Connection[Any], event_id: UUID, filters: dict[str, Any], sort_sql: str, page: int, size: int) -> tuple[list[Mapping[str, Any]], int]:
        predicates = ["event_id = %s"]
        values: list[Any] = [event_id]
        if filters.get("status") is not None:
            predicates.append("status = %s")
            values.append(filters["status"])
        if filters.get("name") is not None:
            predicates.append("name ILIKE %s")
            values.append(f"%{filters['name']}%")
        if filters.get("text") is not None:
            predicates.append("(name ILIKE %s OR email ILIKE %s)")
            needle = f"%{filters['text']}%"
            values.extend((needle, needle))
        where = " WHERE " + " AND ".join(predicates)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM guests" + where, values)
            total = cur.fetchone()[0]
            cur.execute(
                "SELECT id, event_id, name, email, status, created_at, updated_at FROM guests"
                + where + f" ORDER BY {sort_sql} LIMIT %s OFFSET %s",
                [*values, size, (page - 1) * size],
            )
            return list(cur.fetchall()), total

    def lock_event_and_count_accepted(self, conn: Connection[Any], event_id: UUID) -> tuple[int, int] | None:
        """Serialize capacity decisions by locking the event row."""
        with conn.cursor() as cur:
            cur.execute("SELECT capacity FROM events WHERE id = %s FOR UPDATE", (event_id,))
            event = cur.fetchone()
            if not event:
                return None
            cur.execute("SELECT COUNT(*) FROM guests WHERE event_id = %s AND status = 'accepted'", (event_id,))
            return event[0], cur.fetchone()[0]

    def insert(self, conn: Connection[Any], guest: dict[str, Any]) -> Mapping[str, Any]:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO guests (id, event_id, name, email, status, created_at, updated_at) "
                "VALUES (%(id)s, %(event_id)s, %(name)s, %(email)s, %(status)s, %(created_at)s, %(updated_at)s) "
                "RETURNING id, event_id, name, email, status, created_at, updated_at",
                guest,
            )
            return cur.fetchone()

    def update(self, conn: Connection[Any], event_id: UUID, guest_id: UUID, changes: dict[str, Any]) -> Mapping[str, Any]:
        columns = list(changes)
        assignments = ", ".join(f"{column} = %({column})s" for column in columns)
        params = {**changes, "id": guest_id, "event_id": event_id}
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE guests SET " + assignments + " WHERE id = %(id)s AND event_id = %(event_id)s "
                "RETURNING id, event_id, name, email, status, created_at, updated_at",
                params,
            )
            return cur.fetchone()

    def delete(self, conn: Connection[Any], event_id: UUID, guest_id: UUID) -> None:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM guests WHERE id = %s AND event_id = %s", (guest_id, event_id))

    def insert_notification(self, conn: Connection[Any], values: dict[str, Any]) -> None:
        """The schema's unique key makes repeated state notifications idempotent."""
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notifications "
                "(id, event_id, kind, source_type, source_id, state_key, message, read_at, created_at) "
                "VALUES (%(id)s, %(event_id)s, %(kind)s, %(source_type)s, %(source_id)s, "
                "%(state_key)s, %(message)s, NULL, %(created_at)s) "
                "ON CONFLICT (event_id, kind, source_type, source_id, state_key) DO NOTHING",
                values,
            )

    def insert_audit(self, conn: Connection[Any], values: dict[str, Any]) -> None:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO audit_logs "
                "(id, event_id, actor_user_id, resource_type, resource_id, action, details, created_at) "
                "VALUES (%(id)s, %(event_id)s, %(actor_user_id)s, %(resource_type)s, %(resource_id)s, "
                "%(action)s, %(details)s::jsonb, %(created_at)s)",
                {**values, "details": json.dumps(values["details"], default=str)},
            )
