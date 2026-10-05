"""Notification and audit-log resource services and Flask blueprint.

The module deliberately has no application-factory side effects.  The factory injects a
``Database`` in ``app.extensions['services']`` and registers ``notification_audit_bp``.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from threading import Event, Thread, current_thread
from typing import Any
from uuid import uuid4
import logging

from flask import Blueprint, current_app, g, jsonify, request

from .errors import AuthorizationError, NotFoundError, ValidationError
from .security import require_auth


AUDIT_ACTIONS = frozenset({"create", "update", "delete", "status_change"})


notification_audit_bp = Blueprint("notification_audit", __name__)


class NotificationAuditService:
    """Direct-SQL operations for generated notifications and immutable audit logs."""

    def __init__(self, database: Any):
        self.db = database

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        """Convert a psycopg dict row (or compatible mapping) to JSON wire values."""
        result: dict[str, Any] = {}
        for key, value in dict(row).items():
            if isinstance(value, (datetime, date)):
                result[key] = value.isoformat()
            elif isinstance(value, Decimal):
                result[key] = str(value)
            elif hasattr(value, "hex") and value.__class__.__name__ == "UUID":
                result[key] = str(value)
            else:
                result[key] = value
        return result

    def _event_for_owner(self, event_id: str, user_id: str, cursor: Any | None = None) -> None:
        """Raise the API's domain errors, preserving 404-before-403 semantics.

        ``cursor`` is supplied by mutation/scanner callers so every statement takes
        place on their single transaction connection.
        """
        if cursor is None:
            event = self.db.fetchone("SELECT id, owner_id FROM events WHERE id = %s", (event_id,))
        else:
            cursor.execute("SELECT id, owner_id FROM events WHERE id = %s", (event_id,))
            event = cursor.fetchone()
        if event is None:
            raise NotFoundError("Event not found")
        if str(dict(event)["owner_id"]) != str(user_id):
            raise AuthorizationError("You do not own this event")

    @staticmethod
    def _page(page: str | None, size: str | None) -> tuple[int, int]:
        try:
            resolved_page = int(page or "1")
            resolved_size = int(size or "20")
        except (TypeError, ValueError) as exc:
            raise ValidationError("page and size must be integers") from exc
        if resolved_page < 1 or not 1 <= resolved_size <= 100:
            raise ValidationError("page must be positive and size must be between 1 and 100")
        return resolved_page, resolved_size

    @staticmethod
    def _reject_unknown_query(query: dict[str, str], allowed: set[str]) -> None:
        unknown = set(query).difference(allowed)
        if unknown:
            raise ValidationError(f"Unknown query parameter: {sorted(unknown)[0]}")

    def list_notifications(self, event_id: str, user_id: str, query: dict[str, str]) -> dict[str, Any]:
        self._event_for_owner(event_id, user_id)
        self._reject_unknown_query(query, {"page", "size", "sort", "direction", "kind", "sourceType", "read"})
        page, size = self._page(query.get("page"), query.get("size"))
        sort_columns = {"createdAt": "created_at", "kind": "kind", "readAt": "read_at"}
        sort = query.get("sort", "createdAt")
        direction = query.get("direction", "desc").lower()
        if sort not in sort_columns or direction not in {"asc", "desc"}:
            raise ValidationError("Invalid notification sort or direction")
        clauses, params = ["event_id = %s"], [event_id]
        if kind := query.get("kind"):
            clauses.append("kind = %s")
            params.append(kind)
        if source_type := query.get("sourceType"):
            clauses.append("source_type = %s")
            params.append(source_type)
        if read := query.get("read"):
            if read.lower() not in {"true", "false"}:
                raise ValidationError("read must be true or false")
            clauses.append("read_at IS " + ("NOT NULL" if read.lower() == "true" else "NULL"))
        where = " AND ".join(clauses)
        total = dict(self.db.fetchone(f"SELECT count(*) AS total FROM notifications WHERE {where}", tuple(params)))["total"]
        params.extend([size, (page - 1) * size])
        rows = self.db.fetchall(
            f"SELECT id, event_id, kind, source_type, source_id, state_key, message, read_at, created_at "
            f"FROM notifications WHERE {where} ORDER BY {sort_columns[sort]} {direction}, id {direction} LIMIT %s OFFSET %s",
            tuple(params),
        )
        return {"items": [self._notification(row) for row in rows], "total": total, "page": page, "size": size}

    def acknowledge(self, event_id: str, notification_id: str, user_id: str) -> dict[str, Any]:
        # Do not use Database.fetchone/execute in this block: those helpers open a
        # fresh connection, defeating both FOR UPDATE and atomic acknowledgement.
        with self.db.transaction() as connection:
            with connection.cursor() as cursor:
                self._event_for_owner(event_id, user_id, cursor)
                cursor.execute(
                    "SELECT id, event_id, kind, source_type, source_id, state_key, message, read_at, created_at "
                    "FROM notifications WHERE id = %s AND event_id = %s FOR UPDATE",
                    (notification_id, event_id),
                )
                if cursor.fetchone() is None:
                    raise NotFoundError("Notification not found")
                cursor.execute(
                    "UPDATE notifications SET read_at = COALESCE(read_at, NOW()) "
                    "WHERE id = %s AND event_id = %s "
                    "RETURNING id, event_id, kind, source_type, source_id, state_key, message, read_at, created_at",
                    (notification_id, event_id),
                )
                row = cursor.fetchone()
        return self._notification(row)

    def list_audit_logs(self, event_id: str, user_id: str, query: dict[str, str]) -> dict[str, Any]:
        self._event_for_owner(event_id, user_id)
        self._reject_unknown_query(query, {"page", "size", "sort", "direction", "resourceType", "action", "startDate", "endDate"})
        page, size = self._page(query.get("page"), query.get("size"))
        sort_columns = {"createdAt": "created_at", "action": "action", "resourceType": "resource_type"}
        sort, direction = query.get("sort", "createdAt"), query.get("direction", "desc").lower()
        if sort not in sort_columns or direction not in {"asc", "desc"}:
            raise ValidationError("Invalid audit-log sort or direction")
        clauses, params = ["event_id = %s"], [event_id]
        if resource_type := query.get("resourceType"):
            clauses.append("resource_type = %s")
            params.append(resource_type)
        if action := query.get("action"):
            # Keep the filter aligned with the schema and every resource writer.
            # In particular, legacy verbs such as "status" must not silently
            # masquerade as status_change.
            if action not in AUDIT_ACTIONS:
                raise ValidationError("action must be one of: create, update, delete, status_change")
            clauses.append("action = %s")
            params.append(action)
        for argument, op in (("startDate", ">="), ("endDate", "<=")):
            if value := query.get(argument):
                try:
                    datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    raise ValidationError(f"{argument} must be an ISO-8601 datetime")
                clauses.append(f"created_at {op} %s")
                params.append(value)
        where = " AND ".join(clauses)
        total = dict(self.db.fetchone(f"SELECT count(*) AS total FROM audit_logs WHERE {where}", tuple(params)))["total"]
        params.extend([size, (page - 1) * size])
        rows = self.db.fetchall(
            f"SELECT id, event_id, actor_user_id, resource_type, resource_id, action, details, created_at "
            f"FROM audit_logs WHERE {where} ORDER BY {sort_columns[sort]} {direction}, id {direction} LIMIT %s OFFSET %s",
            tuple(params),
        )
        return {"items": [self._audit(row) for row in rows], "total": total, "page": page, "size": size}

    def scan_due_conditions(self) -> int:
        """Create deduplicated task and budget threshold notices in one transaction."""
        created = 0
        with self.db.transaction() as connection:
            # Advisory locks are transaction-scoped.  Every scan query, including the
            # dedupe check and insert, must therefore use this exact cursor.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id, event_id, title, due_at FROM tasks "
                    "WHERE due_at IS NOT NULL AND status <> 'completed' "
                    "AND due_at > NOW() AND due_at <= NOW() + INTERVAL '24 hours'"
                )
                due_tasks = cursor.fetchall()
                cursor.execute(
                    "SELECT id, event_id, title, due_at FROM tasks "
                    "WHERE due_at IS NOT NULL AND status <> 'completed' AND due_at <= NOW()"
                )
                overdue_tasks = cursor.fetchall()
                for task in due_tasks:
                    data = dict(task)
                    state = f"due:{data['due_at'].isoformat()}"
                    created += self._create_once(cursor, data["event_id"], "task_deadline", "task", data["id"], state,
                                                 f"Task '{data['title']}' is due within 24 hours.")
                for task in overdue_tasks:
                    data = dict(task)
                    state = f"overdue:{data['due_at'].isoformat()}"
                    created += self._create_once(cursor, data["event_id"], "task_overdue", "task", data["id"], state,
                                                 f"Task '{data['title']}' is overdue.")
                cursor.execute(
                    "SELECT c.id, c.event_id, c.name, c.planned_amount, COALESCE(SUM(e.amount), 0) AS actual "
                    "FROM budget_categories c LEFT JOIN expenses e ON e.budget_category_id = c.id "
                    "GROUP BY c.id HAVING c.planned_amount > 0 "
                    "AND COALESCE(SUM(e.amount), 0) >= c.planned_amount * 0.9"
                )
                for category in cursor.fetchall():
                    data = dict(category)
                    state = f"{data['actual']}/{data['planned_amount']}"
                    created += self._create_once(cursor, data["event_id"], "budget_threshold", "budget_category", data["id"], state,
                                                 f"Budget category '{data['name']}' has reached 90% of its planned amount.")
        return created

    def _create_once(self, cursor: Any, event_id: Any, kind: str, source_type: str, source_id: Any,
                     state_key: str, message: str) -> int:
        # The schema also has a uniqueness constraint; the advisory lock avoids relying
        # on a conflicting insert and keeps a concurrent scanner's outcome deterministic.
        lock_key = f"notification:{kind}:{source_type}:{source_id}:{state_key}"
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (lock_key,))
        cursor.execute(
            "SELECT id FROM notifications WHERE kind = %s AND source_type = %s AND source_id = %s AND state_key = %s",
            (kind, source_type, source_id, state_key),
        )
        if cursor.fetchone() is not None:
            return 0
        cursor.execute(
            "INSERT INTO notifications (id, event_id, kind, source_type, source_id, state_key, message, read_at, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, NOW())",
            (str(uuid4()), event_id, kind, source_type, source_id, state_key, message),
        )
        return 1

    def _notification(self, row: Any) -> dict[str, Any]:
        data = self._row(row)
        return {"id": data["id"], "eventId": data["event_id"], "kind": data["kind"],
                "sourceType": data["source_type"], "sourceId": data["source_id"], "stateKey": data["state_key"],
                "message": data["message"], "readAt": data["read_at"], "createdAt": data["created_at"]}

    def _audit(self, row: Any) -> dict[str, Any]:
        data = self._row(row)
        return {"id": data["id"], "eventId": data["event_id"], "actorUserId": data["actor_user_id"],
                "resourceType": data["resource_type"], "resourceId": data["resource_id"], "action": data["action"],
                "details": data["details"], "createdAt": data["created_at"]}


def _service() -> NotificationAuditService:
    services = current_app.extensions["services"]
    # The app may store the shared Database directly or this group service after construction.
    return services.get("notification_audit") or services.get("notifications") or NotificationAuditService(services["database"])


@notification_audit_bp.get("/events/<event_id>/notifications")
@require_auth
def get_notifications(event_id: str):
    return jsonify(_service().list_notifications(event_id, g.user_id, request.args.to_dict()))


@notification_audit_bp.patch("/events/<event_id>/notifications/<notification_id>")
@require_auth
def acknowledge_notification(event_id: str, notification_id: str):
    return jsonify(_service().acknowledge(event_id, notification_id, g.user_id))


@notification_audit_bp.get("/events/<event_id>/audit-logs")
@require_auth
def get_audit_logs(event_id: str):
    return jsonify(_service().list_audit_logs(event_id, g.user_id, request.args.to_dict()))


class NotificationScanner:
    """Scheduler-facing scanner. ``run_once`` is convenient for deterministic tests."""
    def __init__(self, database: Any):
        self.service = NotificationAuditService(database)

    def run_once(self) -> int:
        return self.service.scan_due_conditions()


class PeriodicNotificationScanner(NotificationScanner):
    """A stoppable once-per-minute scanner suitable for application lifecycle wiring.

    The factory owns starting it (so workers do not accidentally create duplicate daemon
    threads); database-level advisory locking keeps duplicate scanner instances harmless.
    """
    def __init__(self, database: Any, interval_seconds: float = 60.0, *, enabled: bool = True):
        super().__init__(database)
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self.enabled = enabled
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start once when enabled; return whether a worker is running afterwards."""
        if not self.enabled:
            return False
        if self.is_running:
            return True
        self._stop.clear()
        self._thread = Thread(target=self._loop, name="notification-scanner", daemon=True)
        self._thread.start()
        return True

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        if thread is not None and not thread.is_alive():
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # one bad scan must not permanently stop deadline alerts
                logging.getLogger(__name__).exception("notification scanner failed")
            self._stop.wait(self.interval_seconds)
