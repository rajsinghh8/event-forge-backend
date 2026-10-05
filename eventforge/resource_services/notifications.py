"""Notification and audit resource service contracts and orchestration.

Repository implementations own persistence and must make
:meth:`NotificationAuditRepository.create_notification_for_new_source` atomic:
the notification and its source-state record are committed together.  That
operation is what makes repeated scheduler runs safe.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NotRequired, Protocol, TypedDict

from eventforge.errors import NotFoundError, ValidationError


DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100
DUE_SOON_WINDOW = timedelta(hours=24)


class NotificationDTO(TypedDict):
    """Notification returned to an authenticated recipient."""

    id: str
    recipient_id: str
    kind: str
    title: str
    message: str
    is_read: bool
    created_at: datetime
    read_at: NotRequired[datetime | None]
    task_id: NotRequired[str | None]
    event_id: NotRequired[str | None]


class AuditLogDTO(TypedDict):
    """An immutable audit entry visible only to its owning user."""

    id: str
    owner_id: str
    event_id: str
    action: str
    entity_type: str
    entity_id: str
    occurred_at: datetime
    actor_id: NotRequired[str | None]
    details: NotRequired[dict[str, object]]


class NotificationPageDTO(TypedDict):
    items: list[NotificationDTO]
    total: int
    limit: int
    offset: int


class AuditLogPageDTO(TypedDict):
    items: list[AuditLogDTO]
    total: int
    limit: int
    offset: int


class DueTaskDTO(TypedDict):
    """Minimal task projection required by the periodic notification scan."""

    id: str
    recipient_id: str
    title: str
    due_at: datetime
    event_id: NotRequired[str | None]


class CreateScheduledNotificationDTO(TypedDict):
    """Payload persisted for a task-derived notification source."""

    source_key: str
    recipient_id: str
    kind: str
    title: str
    message: str
    task_id: str
    event_id: NotRequired[str | None]
    created_at: datetime


class ScanResultDTO(TypedDict):
    """Counts produced by one idempotent due-task scan."""

    scanned_due_soon: int
    scanned_overdue: int
    created_due_soon: int
    created_overdue: int


class NotificationAuditRepository(Protocol):
    """Persistence operations used exclusively by ``NotificationResourceService``.

    ``create_notification_for_new_source`` must atomically record ``source_key``
    in the source-state store and insert its notification.  It returns ``None``
    when a prior scan has already recorded that source, rather than raising.
    """

    def list_notifications_for_recipient(
        self, recipient_id: str, *, limit: int, offset: int
    ) -> NotificationPageDTO: ...

    def get_notification_for_recipient(
        self, recipient_id: str, notification_id: str
    ) -> NotificationDTO | None: ...

    def mark_notification_read_for_recipient(
        self, recipient_id: str, notification_id: str, *, read_at: datetime
    ) -> NotificationDTO | None: ...

    def delete_notification_for_recipient(
        self, recipient_id: str, notification_id: str
    ) -> bool: ...

    def list_audit_logs_for_owner(
        self, owner_id: str, *, limit: int, offset: int
    ) -> AuditLogPageDTO: ...

    def list_audit_logs_for_event_owner(
        self, owner_id: str, event_id: str, *, limit: int, offset: int
    ) -> AuditLogPageDTO: ...

    def list_tasks_due_between(
        self, *, starts_at: datetime, ends_at: datetime
    ) -> list[DueTaskDTO]:
        """Return active tasks in the inclusive ``[starts_at, ends_at]`` window."""
        ...

    def list_overdue_tasks(self, *, as_of: datetime) -> list[DueTaskDTO]: ...

    def create_notification_for_new_source(
        self, notification: CreateScheduledNotificationDTO
    ) -> NotificationDTO | None: ...


class NotificationResourceService:
    """Recipient/owner-scoped notification and audit use cases.

    Method contracts:
    * ``list_notifications`` returns an offset page for exactly ``recipient_id``.
    * ``get_notification`` and ``mark_notification_read`` return a notification
      or raise ``NotFoundError`` when it is outside that recipient scope.
    * ``delete_notification`` returns ``None`` or raises ``NotFoundError`` under
      the same scope policy.
    * ``list_audit_logs`` returns only entries owned by ``owner_id``.
    * ``scan_due_task_notifications`` is idempotent for a scan timestamp: source
      keys prevent duplicate due-soon and overdue task notifications.
    """

    def __init__(self, repository: NotificationAuditRepository) -> None:
        self._repository = repository

    def list_notifications(
        self, recipient_id: str, *, limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> NotificationPageDTO:
        self._validate_page(limit=limit, offset=offset)
        return self._repository.list_notifications_for_recipient(
            recipient_id, limit=limit, offset=offset
        )

    def get_notification(self, recipient_id: str, notification_id: str) -> NotificationDTO:
        notification = self._repository.get_notification_for_recipient(
            recipient_id, notification_id
        )
        if notification is None:
            raise NotFoundError("notification not found")
        return notification

    def mark_notification_read(
        self, recipient_id: str, notification_id: str, *, read_at: datetime
    ) -> NotificationDTO:
        notification = self._repository.mark_notification_read_for_recipient(
            recipient_id, notification_id, read_at=read_at
        )
        if notification is None:
            raise NotFoundError("notification not found")
        return notification

    def delete_notification(self, recipient_id: str, notification_id: str) -> None:
        deleted = self._repository.delete_notification_for_recipient(
            recipient_id, notification_id
        )
        if not deleted:
            raise NotFoundError("notification not found")

    def list_audit_logs(
        self, owner_id: str, *, limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> AuditLogPageDTO:
        """Optional global owner list, spanning all events the caller owns."""
        self._validate_page(limit=limit, offset=offset)
        return self._repository.list_audit_logs_for_owner(owner_id, limit=limit, offset=offset)

    def list_event_audit_logs(
        self, owner_id: str, event_id: str, *, limit: int = DEFAULT_PAGE_LIMIT, offset: int = 0
    ) -> AuditLogPageDTO:
        """List audit records for exactly one event, only when the caller owns it."""
        self._validate_page(limit=limit, offset=offset)
        return self._repository.list_audit_logs_for_event_owner(owner_id, event_id, limit=limit, offset=offset)

    def scan_due_task_notifications(self, *, scanned_at: datetime) -> ScanResultDTO:
        """Create task reminders due within 24 hours and overdue reminders.

        The due-soon window is inclusive and begins at ``scanned_at``; the
        overdue query must return only tasks due before that instant. Repository
        task queries must exclude completed or cancelled tasks. The atomic
        source-state operation is deliberately used for every candidate, so
        concurrent scheduler workers are also safe.
        """
        due_soon = self._repository.list_tasks_due_between(
            starts_at=scanned_at, ends_at=scanned_at + DUE_SOON_WINDOW
        )
        overdue = self._repository.list_overdue_tasks(as_of=scanned_at)
        created_due_soon = self._create_task_notifications(
            due_soon, kind="task_due_soon", scanned_at=scanned_at
        )
        created_overdue = self._create_task_notifications(
            overdue, kind="task_overdue", scanned_at=scanned_at
        )
        return {
            "scanned_due_soon": len(due_soon),
            "scanned_overdue": len(overdue),
            "created_due_soon": created_due_soon,
            "created_overdue": created_overdue,
        }

    def _create_task_notifications(
        self, tasks: list[DueTaskDTO], *, kind: str, scanned_at: datetime
    ) -> int:
        created = 0
        for task in tasks:
            notification: CreateScheduledNotificationDTO = {
                "source_key": f"{kind}:task:{task['id']}",
                "recipient_id": task["recipient_id"],
                "kind": kind,
                "title": "Task due soon" if kind == "task_due_soon" else "Task overdue",
                "message": self._task_message(task, overdue=kind == "task_overdue"),
                "task_id": task["id"],
                "created_at": scanned_at,
            }
            if "event_id" in task:
                notification["event_id"] = task["event_id"]
            if self._repository.create_notification_for_new_source(notification) is not None:
                created += 1
        return created

    @staticmethod
    def _task_message(task: DueTaskDTO, *, overdue: bool) -> str:
        status = "is overdue" if overdue else "is due within 24 hours"
        return f"Task '{task['title']}' {status}."

    @staticmethod
    def _validate_page(*, limit: int, offset: int) -> None:
        if not 1 <= limit <= MAX_PAGE_LIMIT:
            raise ValidationError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")
        if offset < 0:
            raise ValidationError("offset must be non-negative")
