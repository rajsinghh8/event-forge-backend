"""Oracle-bound persistence primitives for Event aggregates.

Every user-controlled value is passed through a named bind; SQL identifiers are
selected only from module constants.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from .domain.events import Event, EventStatus
from .event_dto import CreateEvent, EventFilters, OffsetPage, UpdateEvent


class OracleCursor(Protocol):
    def execute(self, statement: str, parameters: Mapping[str, Any] | None = None) -> Any: ...
    def fetchone(self) -> Mapping[str, Any] | None: ...
    def fetchall(self) -> list[Mapping[str, Any]]: ...
    def close(self) -> None: ...


class OracleConnection(Protocol):
    def cursor(self) -> OracleCursor: ...


class EventRepository:
    _COLUMNS = """event_id, owner_id, name, event_datetime, venue, capacity,
                  budget_limit, status, description, created_at, updated_at"""

    def _one(self, connection: OracleConnection, sql: str, binds: Mapping[str, Any]) -> Mapping[str, Any] | None:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, binds)
            return cursor.fetchone()
        finally:
            cursor.close()

    def _many(self, connection: OracleConnection, sql: str, binds: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, binds)
            return cursor.fetchall()
        finally:
            cursor.close()

    @staticmethod
    def _event(row: Mapping[str, Any]) -> Event:
        # python-oracledb may expose fetched mapping keys in either case.
        def value(name: str) -> Any:
            return row.get(name) if name in row else row[name.upper()]
        return Event(
            id=UUID(str(value("event_id"))), owner_id=str(value("owner_id")), name=str(value("name")),
            event_datetime=value("event_datetime"), venue=value("venue"),
            capacity=(None if value("capacity") is None else int(value("capacity"))),
            budget_limit=(None if value("budget_limit") is None else Decimal(str(value("budget_limit")))),
            status=EventStatus(str(value("status"))), description=value("description"),
            created_at=value("created_at"), updated_at=value("updated_at"),
        )

    def create(self, connection: OracleConnection, *, event_id: UUID, owner_id: str, command: CreateEvent) -> Event:
        sql = f"""INSERT INTO events ({self._COLUMNS})
            VALUES (:event_id, :owner_id, :name, :event_datetime, :venue, :capacity,
                    :budget_limit, :status, :description, SYSTIMESTAMP, SYSTIMESTAMP)"""
        cursor = connection.cursor()
        try:
            cursor.execute(sql, {
                "event_id": str(event_id), "owner_id": owner_id, "name": command.name,
                "event_datetime": command.event_datetime, "venue": command.venue,
                "capacity": command.capacity, "budget_limit": command.budget_limit,
                "status": command.status.value, "description": command.description,
            })
        finally:
            cursor.close()
        event = self.get_owned(connection, event_id=event_id, owner_id=owner_id)
        assert event is not None  # Enforces expected Oracle read-your-own-write semantics.
        return event

    def get_owned(self, connection: OracleConnection, *, event_id: UUID, owner_id: str) -> Event | None:
        row = self._one(connection, f"SELECT {self._COLUMNS} FROM events WHERE event_id = :event_id AND owner_id = :owner_id", {
            "event_id": str(event_id), "owner_id": owner_id,
        })
        return None if row is None else self._event(row)

    def list_owned(self, connection: OracleConnection, *, owner_id: str, filters: EventFilters, page: OffsetPage) -> tuple[list[Event], int]:
        predicates = ["owner_id = :owner_id"]
        binds: dict[str, Any] = {"owner_id": owner_id}
        if filters.status is not None:
            predicates.append("status = :status")
            binds["status"] = filters.status.value
        if filters.search is not None:
            predicates.append("(UPPER(name) LIKE UPPER(:search) ESCAPE '\\' OR UPPER(venue) LIKE UPPER(:search) ESCAPE '\\')")
            binds["search"] = "%" + filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if filters.starts_from is not None:
            predicates.append("event_datetime >= :starts_from")
            binds["starts_from"] = filters.starts_from
        if filters.starts_to is not None:
            predicates.append("event_datetime <= :starts_to")
            binds["starts_to"] = filters.starts_to
        where = " WHERE " + " AND ".join(predicates)
        total_row = self._one(connection, "SELECT COUNT(*) AS total FROM events" + where, binds)
        assert total_row is not None
        total = int(total_row.get("total", total_row.get("TOTAL", 0)))
        binds.update({"offset": page.offset, "page_size": page.page_size})
        rows = self._many(connection, f"SELECT {self._COLUMNS} FROM events{where} ORDER BY event_datetime ASC, event_id ASC OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY", binds)
        return [self._event(row) for row in rows], total

    def update_owned(self, connection: OracleConnection, *, event_id: UUID, owner_id: str, command: UpdateEvent) -> Event | None:
        assignments: list[str] = []
        binds: dict[str, Any] = {"event_id": str(event_id), "owner_id": owner_id}
        for field in ("name", "event_datetime", "venue", "capacity", "budget_limit", "status", "description"):
            value = getattr(command, field)
            if value is not None or field in command.clear:
                assignments.append(f"{field} = :{field}")
                binds[field] = value.value if field == "status" and value is not None else value
        assignments.append("updated_at = SYSTIMESTAMP")
        cursor = connection.cursor()
        try:
            cursor.execute(f"UPDATE events SET {', '.join(assignments)} WHERE event_id = :event_id AND owner_id = :owner_id", binds)
            if getattr(cursor, "rowcount", 1) == 0:
                return None
        finally:
            cursor.close()
        return self.get_owned(connection, event_id=event_id, owner_id=owner_id)

    def delete_owned(self, connection: OracleConnection, *, event_id: UUID, owner_id: str) -> bool:
        cursor = connection.cursor()
        try:
            cursor.execute("DELETE FROM events WHERE event_id = :event_id AND owner_id = :owner_id", {"event_id": str(event_id), "owner_id": owner_id})
            return getattr(cursor, "rowcount", 0) == 1
        finally:
            cursor.close()

    def aggregate_inputs(self, connection: OracleConnection, *, event_id: UUID, owner_id: str) -> tuple[int, Decimal] | None:
        """Return attendee and expense sums only after proving event ownership.

        Correlated subqueries preserve an event with no related rows. The audit
        service invokes this inside the same transaction as its aggregate read.
        """
        row = self._one(connection, """
            SELECT (SELECT COUNT(*) FROM event_attendees ea WHERE ea.event_id = e.event_id) AS attendee_count,
                   NVL((SELECT SUM(ex.amount) FROM expenses ex WHERE ex.event_id = e.event_id), 0) AS actual_spend
            FROM events e WHERE e.event_id = :event_id AND e.owner_id = :owner_id
            """, {"event_id": str(event_id), "owner_id": owner_id})
        if row is None:
            return None
        attendees = int(row.get("attendee_count", row.get("ATTENDEE_COUNT", 0)))
        spend = Decimal(str(row.get("actual_spend", row.get("ACTUAL_SPEND", 0))))
        return attendees, spend
