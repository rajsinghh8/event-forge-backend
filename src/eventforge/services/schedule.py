"""Pure application service for schedule entries."""
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from eventforge.domain.errors import ConflictError, NotFoundError
from eventforge.domain.schedule import ScheduleEntry
from eventforge.repository.schedule import ScheduleRepository


class ScheduleService:
    def __init__(self, repository: ScheduleRepository):
        self.repository = repository

    def create(self, event_id: str, title: str, starts_at: datetime, ends_at: datetime, description: str | None = None) -> ScheduleEntry:
        entry = ScheduleEntry(str(uuid4()), event_id, title, starts_at, ends_at, description)
        self._ensure_open(entry)
        return self.repository.add(entry)

    def update(self, schedule_id: str, *, title: str | None = None, starts_at: datetime | None = None, ends_at: datetime | None = None, description: str | None = None) -> ScheduleEntry:
        current = self.repository.get(schedule_id)
        if current is None:
            raise NotFoundError("schedule entry not found")
        candidate = replace(current, title=title if title is not None else current.title,
                            starts_at=starts_at if starts_at is not None else current.starts_at,
                            ends_at=ends_at if ends_at is not None else current.ends_at,
                            description=description if description is not None else current.description)
        self._ensure_open(candidate, ignored_id=current.id)
        return self.repository.update(candidate)

    def delete(self, schedule_id: str) -> None:
        if not self.repository.delete(schedule_id):
            raise NotFoundError("schedule entry not found")

    def _ensure_open(self, candidate: ScheduleEntry, ignored_id: str | None = None) -> None:
        # Oracle implementations may lock the matching rows in the surrounding transaction.
        overlaps = self.repository.overlapping(candidate.event_id, candidate.starts_at, candidate.ends_at, lock=True)
        if any(existing.id != ignored_id for existing in overlaps):
            raise ConflictError("schedule entry overlaps an existing entry")
