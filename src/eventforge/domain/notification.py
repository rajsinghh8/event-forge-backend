"""Notification aggregate and supported notification types."""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .errors import ValidationError


class NotificationType(StrEnum):
    DEADLINE = "deadline"
    INVITATION = "invitation"
    OVERDUE_TASK = "overdue-task"
    BUDGET_WARNING = "budget-warning"


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    recipient_id: str
    type: NotificationType
    title: str
    body: str
    created_at: datetime
    deduplication_key: str
    read_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.recipient_id:
            raise ValidationError("recipient_id is required")
        if not isinstance(self.type, NotificationType):
            try:
                object.__setattr__(self, "type", NotificationType(self.type))
            except ValueError as exc:
                raise ValidationError("unsupported notification type") from exc
        if not self.title or not self.title.strip():
            raise ValidationError("notification title is required")
        if not self.deduplication_key or not self.deduplication_key.strip():
            raise ValidationError("deduplication_key is required")

    @property
    def is_read(self) -> bool:
        return self.read_at is not None
