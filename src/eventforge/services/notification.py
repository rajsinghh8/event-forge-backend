"""Notification delivery/read-state service."""
from datetime import datetime, timezone
from uuid import uuid4

from eventforge.domain.errors import NotFoundError
from eventforge.domain.notification import Notification, NotificationType
from eventforge.repository.notification import NotificationRepository


class NotificationService:
    def __init__(self, repository: NotificationRepository, clock=None):
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def notify(self, recipient_id: str, type: NotificationType | str, title: str, body: str, deduplication_key: str) -> Notification:
        """Create once per recipient/key; retrying returns the original notification."""
        existing = self.repository.find_by_deduplication(recipient_id, deduplication_key)
        if existing is not None:
            return existing
        notification = Notification(str(uuid4()), recipient_id, NotificationType(type), title, body,
                                    self.clock(), deduplication_key)
        return self.repository.add(notification)

    def mark_read(self, notification_id: str) -> Notification:
        # Repository uses COALESCE, making this operation idempotent and preserving first-read time.
        notification = self.repository.mark_read(notification_id, self.clock())
        if notification is None:
            raise NotFoundError("notification not found")
        return notification

    def list_for_recipient(self, recipient_id: str, *, unread_only: bool = False) -> list[Notification]:
        return self.repository.list_for_recipient(recipient_id, unread_only=unread_only)
