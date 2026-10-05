"""Schedule domain model. Time ranges deliberately use the half-open [start, end) rule."""
from dataclasses import dataclass
from datetime import datetime

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class ScheduleEntry:
    id: str
    event_id: str
    title: str
    starts_at: datetime
    ends_at: datetime
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValidationError("event_id is required")
        if not self.title or not self.title.strip():
            raise ValidationError("schedule title is required")
        if self.starts_at >= self.ends_at:
            raise ValidationError("schedule start must be before end")
        if (self.starts_at.tzinfo is None) != (self.ends_at.tzinfo is None):
            raise ValidationError("schedule timestamps must have matching timezone awareness")

    def overlaps(self, other: "ScheduleEntry") -> bool:
        """True only for intersection with positive duration.

        Equality at a boundary is intentionally not an overlap, allowing one
        entry to end exactly when its successor starts.
        """
        return self.starts_at < other.ends_at and self.ends_at > other.starts_at
