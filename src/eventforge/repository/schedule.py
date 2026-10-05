"""Schedule persistence ports and Oracle named-bind statements."""
from typing import Any, Protocol

from eventforge.domain.schedule import ScheduleEntry


class ScheduleRepository(Protocol):
    def overlapping(self, event_id: str, starts_at: object, ends_at: object, *, lock: bool = False) -> list[ScheduleEntry]: ...
    def get(self, schedule_id: str) -> ScheduleEntry | None: ...
    def add(self, entry: ScheduleEntry) -> ScheduleEntry: ...
    def update(self, entry: ScheduleEntry) -> ScheduleEntry: ...
    def delete(self, schedule_id: str) -> bool: ...


FIND_OVERLAPS_SQL = """
SELECT id, event_id, title, starts_at, ends_at, description
  FROM schedules
 WHERE event_id = :event_id
   AND starts_at < :ends_at
   AND ends_at > :starts_at
"""
INSERT_SQL = """
INSERT INTO schedules (id, event_id, title, starts_at, ends_at, description)
VALUES (:id, :event_id, :title, :starts_at, :ends_at, :description)
"""
UPDATE_SQL = """
UPDATE schedules SET title = :title, starts_at = :starts_at, ends_at = :ends_at,
                     description = :description
 WHERE id = :id
"""


class OracleScheduleRepository:
    """Thin direct-oracledb adapter; connection lifecycle belongs to the caller."""

    def __init__(self, connection: Any):
        self.connection = connection

    @staticmethod
    def _entry(row: tuple[Any, ...]) -> ScheduleEntry:
        return ScheduleEntry(*row)

    def overlapping(self, event_id: str, starts_at: object, ends_at: object, *, lock: bool = False) -> list[ScheduleEntry]:
        sql = FIND_OVERLAPS_SQL + (" FOR UPDATE" if lock else "")
        cursor = self.connection.cursor()
        cursor.execute(sql, {"event_id": event_id, "starts_at": starts_at, "ends_at": ends_at})
        return [self._entry(row) for row in cursor]

    def get(self, schedule_id: str) -> ScheduleEntry | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT id, event_id, title, starts_at, ends_at, description FROM schedules WHERE id = :id", {"id": schedule_id})
        row = cursor.fetchone()
        return self._entry(row) if row else None

    def add(self, entry: ScheduleEntry) -> ScheduleEntry:
        cursor = self.connection.cursor()
        cursor.execute(INSERT_SQL, entry.__dict__ if hasattr(entry, "__dict__") else {name: getattr(entry, name) for name in entry.__dataclass_fields__})
        return entry

    def update(self, entry: ScheduleEntry) -> ScheduleEntry:
        params = {name: getattr(entry, name) for name in entry.__dataclass_fields__}
        cursor = self.connection.cursor()
        cursor.execute(UPDATE_SQL, params)
        return entry

    def delete(self, schedule_id: str) -> bool:
        cursor = self.connection.cursor()
        cursor.execute("DELETE FROM schedules WHERE id = :id", {"id": schedule_id})
        return cursor.rowcount == 1
