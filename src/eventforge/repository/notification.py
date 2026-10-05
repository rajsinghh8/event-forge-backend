"""Notification persistence port and Oracle SQL using named binds."""
from typing import Any, Protocol

from eventforge.domain.notification import Notification


class NotificationRepository(Protocol):
    def find_by_deduplication(self, recipient_id: str, deduplication_key: str) -> Notification | None: ...
    def add(self, notification: Notification) -> Notification: ...
    def get(self, notification_id: str) -> Notification | None: ...
    def mark_read(self, notification_id: str, read_at: object) -> Notification | None: ...
    def list_for_recipient(self, recipient_id: str, *, unread_only: bool = False) -> list[Notification]: ...

FIND_DEDUP_SQL = """SELECT id, recipient_id, type, title, body, created_at, deduplication_key, read_at
FROM notifications WHERE recipient_id = :recipient_id AND deduplication_key = :deduplication_key"""
INSERT_SQL = """INSERT INTO notifications
(id, recipient_id, type, title, body, created_at, deduplication_key, read_at)
VALUES (:id, :recipient_id, :type, :title, :body, :created_at, :deduplication_key, :read_at)"""
MARK_READ_SQL = "UPDATE notifications SET read_at = COALESCE(read_at, :read_at) WHERE id = :id"


class OracleNotificationRepository:
    def __init__(self, connection: Any):
        self.connection = connection

    @staticmethod
    def _notification(row: tuple[Any, ...]) -> Notification:
        return Notification(*row)

    def find_by_deduplication(self, recipient_id: str, deduplication_key: str) -> Notification | None:
        cursor = self.connection.cursor()
        cursor.execute(FIND_DEDUP_SQL, {"recipient_id": recipient_id, "deduplication_key": deduplication_key})
        row = cursor.fetchone()
        return self._notification(row) if row else None

    def add(self, notification: Notification) -> Notification:
        params = {name: getattr(notification, name) for name in notification.__dataclass_fields__}
        params["type"] = notification.type.value
        self.connection.cursor().execute(INSERT_SQL, params)
        return notification

    def get(self, notification_id: str) -> Notification | None:
        cursor = self.connection.cursor()
        cursor.execute("SELECT id, recipient_id, type, title, body, created_at, deduplication_key, read_at FROM notifications WHERE id=:id", {"id": notification_id})
        row = cursor.fetchone()
        return self._notification(row) if row else None

    def mark_read(self, notification_id: str, read_at: object) -> Notification | None:
        self.connection.cursor().execute(MARK_READ_SQL, {"id": notification_id, "read_at": read_at})
        return self.get(notification_id)

    def list_for_recipient(self, recipient_id: str, *, unread_only: bool = False) -> list[Notification]:
        sql = "SELECT id, recipient_id, type, title, body, created_at, deduplication_key, read_at FROM notifications WHERE recipient_id=:recipient_id"
        if unread_only:
            sql += " AND read_at IS NULL"
        sql += " ORDER BY created_at DESC, id DESC"
        cursor = self.connection.cursor()
        cursor.execute(sql, {"recipient_id": recipient_id})
        return [self._notification(row) for row in cursor]
