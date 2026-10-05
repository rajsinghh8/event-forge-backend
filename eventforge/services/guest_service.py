"""Guest business rules, ownership checks, and transactional side effects."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from eventforge.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from eventforge.repositories.guest_repository import GuestRepository


class GuestService:
    """Coordinates guest persistence with capacity, audit, and notification rules."""

    VALID_STATUSES = frozenset({"invited", "accepted", "declined", "cancelled"})
    SORT_COLUMNS = {
        "name": "name",
        "email": "email",
        "status": "status",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
    }

    def __init__(self, database: Any, repository: GuestRepository | None = None) -> None:
        self._database = database
        self._repository = repository or GuestRepository()

    def list(self, event_id: UUID, user_id: UUID, filters: dict[str, Any], page: int, size: int, sort: str, direction: str) -> dict[str, Any]:
        sort_sql = f"{self.SORT_COLUMNS[sort]} {direction}"
        with self._database.transaction() as conn:
            self._require_event_owner(conn, event_id, user_id)
            rows, total = self._repository.list(conn, event_id, filters, sort_sql, page, size)
        return {"items": [self._wire(row) for row in rows], "total": total, "page": page, "size": size}

    def get(self, event_id: UUID, guest_id: UUID, user_id: UUID) -> dict[str, Any]:
        with self._database.transaction() as conn:
            self._require_event_owner(conn, event_id, user_id)
            row = self._repository.get(conn, event_id, guest_id)
            if row is None:
                raise NotFoundError("Guest not found")
            return self._wire(row)

    def create(self, event_id: UUID, user_id: UUID, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = self._validate_create(payload)
        now = datetime.now(UTC)
        guest = {"id": uuid4(), "event_id": event_id, **data, "created_at": now, "updated_at": now}
        with self._database.transaction() as conn:
            self._require_event_owner(conn, event_id, user_id)
            if guest["status"] == "accepted":
                self._assert_capacity(conn, event_id)
            row = self._repository.insert(conn, guest)
            self._notify(conn, row, "created", now)
            self._audit(conn, event_id, user_id, row["id"], "create", {"guest": self._wire(row)}, now)
        return self._wire(row)

    def update(self, event_id: UUID, guest_id: UUID, user_id: UUID, payload: Mapping[str, Any]) -> dict[str, Any]:
        changes = self._validate_update(payload)
        with self._database.transaction() as conn:
            self._require_event_owner(conn, event_id, user_id)
            old = self._repository.get(conn, event_id, guest_id, lock=True)
            if old is None:
                raise NotFoundError("Guest not found")
            if changes.get("status") == "accepted" and old["status"] != "accepted":
                self._assert_capacity(conn, event_id)
            changes["updated_at"] = datetime.now(UTC)
            row = self._repository.update(conn, event_id, guest_id, changes)
            status_changed = row["status"] != old["status"]
            if status_changed:
                self._notify(conn, row, old["status"], changes["updated_at"])
            self._audit(
                conn, event_id, user_id, guest_id, "status_change" if status_changed else "update",
                {"before": self._wire(old), "after": self._wire(row)}, changes["updated_at"],
            )
        return self._wire(row)

    def delete(self, event_id: UUID, guest_id: UUID, user_id: UUID) -> None:
        now = datetime.now(UTC)
        with self._database.transaction() as conn:
            self._require_event_owner(conn, event_id, user_id)
            row = self._repository.get(conn, event_id, guest_id, lock=True)
            if row is None:
                raise NotFoundError("Guest not found")
            self._repository.delete(conn, event_id, guest_id)
            self._audit(conn, event_id, user_id, guest_id, "delete", {"guest": self._wire(row)}, now)

    def _require_event_owner(self, conn: Any, event_id: UUID, user_id: UUID) -> None:
        owner_id = self._repository.event_owner(conn, event_id)
        if owner_id is None:
            raise NotFoundError("Event not found")
        if owner_id != user_id:
            raise ForbiddenError("You do not have access to this event")

    def _assert_capacity(self, conn: Any, event_id: UUID) -> None:
        locked = self._repository.lock_event_and_count_accepted(conn, event_id)
        if locked is None:
            raise NotFoundError("Event not found")
        capacity, accepted = locked
        if accepted >= capacity:
            raise ConflictError("Event capacity has been reached")

    def _notify(self, conn: Any, guest: Mapping[str, Any], prior_state: str, now: datetime) -> None:
        # state_key includes the relevant RSVP state, so a transition back to a
        # previously notified state remains de-duplicated by the database key.
        current = guest["status"]
        self._repository.insert_notification(conn, {
            "id": uuid4(), "event_id": guest["event_id"], "kind": "guest_rsvp",
            "source_type": "guest", "source_id": guest["id"], "state_key": current,
            "message": f"Guest {guest['name']} is {current}", "created_at": now,
        })

    def _audit(self, conn: Any, event_id: UUID, actor_id: UUID, guest_id: UUID, action: str, details: dict[str, Any], now: datetime) -> None:
        self._repository.insert_audit(conn, {
            "id": uuid4(), "event_id": event_id, "actor_user_id": actor_id,
            "resource_type": "guest", "resource_id": guest_id, "action": action,
            "details": details, "created_at": now,
        })

    def _validate_create(self, payload: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(payload, Mapping):
            raise ValidationError("Request body must be a JSON object")
        required = ("name", "email")
        missing = [field for field in required if field not in payload]
        if missing:
            raise ValidationError(f"Missing required field: {missing[0]}")
        unexpected = set(payload) - {"name", "email", "status"}
        if unexpected:
            raise ValidationError(f"Unknown field: {sorted(unexpected)[0]}")
        data = self._validate_fields(payload, allow_empty=False)
        data.setdefault("status", "invited")
        return data

    def _validate_update(self, payload: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(payload, Mapping) or not payload:
            raise ValidationError("Request body must contain at least one updatable field")
        unexpected = set(payload) - {"name", "email", "status"}
        if unexpected:
            raise ValidationError(f"Unknown field: {sorted(unexpected)[0]}")
        return self._validate_fields(payload, allow_empty=False)

    def _validate_fields(self, payload: Mapping[str, Any], *, allow_empty: bool) -> dict[str, str]:
        result: dict[str, str] = {}
        for field in ("name", "email"):
            if field in payload:
                value = payload[field]
                if not isinstance(value, str) or (not allow_empty and not value.strip()):
                    raise ValidationError(f"{field} must be a non-empty string")
                result[field] = value.strip()
        if "email" in result and ("@" not in result["email"] or result["email"].startswith("@")):
            raise ValidationError("email must be a valid email address")
        if "status" in payload:
            status = payload["status"]
            if not isinstance(status, str) or status not in self.VALID_STATUSES:
                raise ValidationError("status must be invited, accepted, declined, or cancelled")
            result["status"] = status
        return result

    @staticmethod
    def _wire(row: Mapping[str, Any]) -> dict[str, Any]:
        def iso(value: Any) -> Any:
            return value.isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value
        return {"id": str(row["id"]), "eventId": str(row["event_id"]), "name": row["name"],
                "email": row["email"], "status": row["status"], "createdAt": iso(row["created_at"]),
                "updatedAt": iso(row["updated_at"])}
