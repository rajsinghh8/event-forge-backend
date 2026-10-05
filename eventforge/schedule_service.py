"""Business rules and response shaping for ScheduleItem resources."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import date, datetime
import json
from typing import Any
from uuid import UUID, uuid4

from .errors import BusinessRuleError, ForbiddenError, NotFoundError, ValidationError
from .schedule_repository import ScheduleRepository


_SORT_COLUMNS = {
    "name": "name",
    "start_at": "start_at",
    "end_at": "end_at",
    "created_at": "created_at",
    "updated_at": "updated_at",
}
_ALLOWED_FIELDS = {"name", "description", "start_at", "end_at"}


class ScheduleService:
    """Owner-scoped schedule CRUD using an injected Database instance."""

    def __init__(self, database: Any, repository: ScheduleRepository | None = None) -> None:
        self._database = database
        self._repository = repository or ScheduleRepository(database)

    @contextmanager
    def _cursor(self, *, write: bool = False) -> Iterator[Any]:
        manager = self._database.transaction() if write else self._database.connection()
        with manager as connection:
            # Database implementations may yield either a connection or a cursor.
            if hasattr(connection, "execute"):
                yield connection
            else:
                with connection.cursor() as cursor:
                    yield cursor

    @staticmethod
    def _uuid(value: UUID | str, field: str) -> UUID:
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field} must be a valid UUID") from exc

    @staticmethod
    def _datetime(value: Any, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be an ISO-8601 datetime")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{field} must be an ISO-8601 datetime") from exc
        # The API accepts ISO-8601 local timestamps as well as offset-aware
        # timestamps; PostgreSQL applies the configured database timezone for
        # local values.  Both endpoints are compared as datetimes in SQL.
        return parsed

    @staticmethod
    def _date(value: Any, field: str) -> date:
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be an ISO-8601 date")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(f"{field} must be an ISO-8601 date") from exc

    @staticmethod
    def _string(value: Any, field: str, *, required: bool = False, nullable: bool = False) -> str | None:
        if value is None and nullable:
            return None
        if not isinstance(value, str):
            raise ValidationError(f"{field} must be a string")
        value = value.strip()
        if required and not value:
            raise ValidationError(f"{field} is required")
        if len(value) > 5000:
            raise ValidationError(f"{field} is too long")
        return value

    @staticmethod
    def _row(row: Mapping[str, Any]) -> dict[str, Any]:
        def value(item: Any) -> Any:
            if isinstance(item, datetime):
                return item.isoformat()
            if isinstance(item, UUID):
                return str(item)
            return item
        return {key: value(item) for key, item in row.items()}

    def _require_event(self, cursor: Any, owner_id: UUID, event_id: UUID) -> None:
        event = self._repository.event_owner(cursor, event_id)
        if event is None:
            raise NotFoundError("Event not found")
        if str(event["owner_id"]) != str(owner_id):
            raise ForbiddenError("You do not own this event")

    @staticmethod
    def _assert_interval(start_at: datetime, end_at: datetime) -> None:
        if start_at >= end_at:
            raise ValidationError("start_at must precede end_at")

    def _assert_no_overlap(self, cursor: Any, event_id: UUID, start_at: datetime, end_at: datetime, exclude_id: UUID | None = None) -> None:
        # This is the half-open rule [start_at, end_at): touching endpoints are legal.
        if self._repository.find_overlap(cursor, event_id, start_at, end_at, exclude_id=exclude_id):
            raise BusinessRuleError("Schedule item overlaps an existing schedule item")

    def _audit(self, cursor: Any, event_id: UUID, owner_id: UUID, item_id: UUID, action: str, details: Mapping[str, Any]) -> None:
        self._repository.insert_audit(
            cursor,
            audit_id=uuid4(),
            event_id=event_id,
            actor_user_id=owner_id,
            resource_id=item_id,
            action=action,
            details_json=json.dumps(details, default=str, separators=(",", ":")),
        )

    def list(self, owner_id: UUID | str, event_id: UUID | str, query: Mapping[str, Any]) -> dict[str, Any]:
        owner = self._uuid(owner_id, "user id")
        event = self._uuid(event_id, "eventId")
        page = self._positive_int(query.get("page", 1), "page", maximum=1_000_000)
        size = self._positive_int(query.get("size", 20), "size", maximum=100)
        sort = self._sort(query.get("sort", "start_at"))
        text = self._optional_query(query.get("text"), "text")
        name = self._optional_query(query.get("name"), "name")
        start_date = self._date(query["startDate"], "startDate") if query.get("startDate") else None
        end_date = self._date(query["endDate"], "endDate") if query.get("endDate") else None
        if start_date and end_date and start_date > end_date:
            raise ValidationError("startDate must not be after endDate")
        with self._cursor() as cursor:
            self._require_event(cursor, owner, event)
            rows, total = self._repository.list(cursor, event, page=page, size=size, sort_sql=sort, text=text, name=name, start_date=start_date, end_date=end_date)
        return {"items": [self._row(row) for row in rows], "total": total, "page": page, "size": size}

    def create(self, owner_id: UUID | str, event_id: UUID | str, payload: Mapping[str, Any]) -> dict[str, Any]:
        event, owner = self._uuid(event_id, "eventId"), self._uuid(owner_id, "user id")
        data = self._create_data(payload)
        with self._cursor(write=True) as cursor:
            self._require_event(cursor, owner, event)
            self._assert_no_overlap(cursor, event, data["start_at"], data["end_at"])
            row = self._repository.insert(cursor, {"id": uuid4(), "event_id": event, **data})
            self._audit(cursor, event, owner, row["id"], "create", {"after": self._row(row)})
        return self._row(row)

    def get(self, owner_id: UUID | str, event_id: UUID | str, item_id: UUID | str) -> dict[str, Any]:
        owner, event, item = self._uuid(owner_id, "user id"), self._uuid(event_id, "eventId"), self._uuid(item_id, "scheduleItemId")
        with self._cursor() as cursor:
            self._require_event(cursor, owner, event)
            row = self._repository.get(cursor, event, item)
            if row is None:
                raise NotFoundError("Schedule item not found")
        return self._row(row)

    def update(self, owner_id: UUID | str, event_id: UUID | str, item_id: UUID | str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or not payload:
            raise ValidationError("Request body must contain at least one editable field")
        unknown = set(payload) - _ALLOWED_FIELDS
        if unknown:
            raise ValidationError(f"Unknown field: {sorted(unknown)[0]}")
        owner, event, item = self._uuid(owner_id, "user id"), self._uuid(event_id, "eventId"), self._uuid(item_id, "scheduleItemId")
        with self._cursor(write=True) as cursor:
            self._require_event(cursor, owner, event)
            before = self._repository.get(cursor, event, item, for_update=True)
            if before is None:
                raise NotFoundError("Schedule item not found")
            values = self._merged_data(before, payload)
            self._assert_interval(values["start_at"], values["end_at"])
            self._assert_no_overlap(cursor, event, values["start_at"], values["end_at"], exclude_id=item)
            row = self._repository.update(cursor, item, values)
            self._audit(cursor, event, owner, item, "update", {"before": self._row(before), "after": self._row(row)})
        return self._row(row)

    def delete(self, owner_id: UUID | str, event_id: UUID | str, item_id: UUID | str) -> None:
        owner, event, item = self._uuid(owner_id, "user id"), self._uuid(event_id, "eventId"), self._uuid(item_id, "scheduleItemId")
        with self._cursor(write=True) as cursor:
            self._require_event(cursor, owner, event)
            before = self._repository.get(cursor, event, item, for_update=True)
            if before is None:
                raise NotFoundError("Schedule item not found")
            self._repository.delete(cursor, event, item)
            self._audit(cursor, event, owner, item, "delete", {"before": self._row(before)})

    def _create_data(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValidationError("Request body must be a JSON object")
        unknown = set(payload) - _ALLOWED_FIELDS
        if unknown:
            raise ValidationError(f"Unknown field: {sorted(unknown)[0]}")
        for field in ("name", "start_at", "end_at"):
            if field not in payload:
                raise ValidationError(f"{field} is required")
        data = {
            "name": self._string(payload["name"], "name", required=True),
            "description": self._string(payload.get("description"), "description", nullable=True) if "description" in payload else None,
            "start_at": self._datetime(payload["start_at"], "start_at"),
            "end_at": self._datetime(payload["end_at"], "end_at"),
        }
        self._assert_interval(data["start_at"], data["end_at"])
        return data

    def _merged_data(self, before: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "name": self._string(payload["name"], "name", required=True) if "name" in payload else before["name"],
            "description": self._string(payload["description"], "description", nullable=True) if "description" in payload else before["description"],
            "start_at": self._datetime(payload["start_at"], "start_at") if "start_at" in payload else before["start_at"],
            "end_at": self._datetime(payload["end_at"], "end_at") if "end_at" in payload else before["end_at"],
        }

    @staticmethod
    def _positive_int(value: Any, field: str, *, maximum: int) -> int:
        if isinstance(value, bool):
            raise ValidationError(f"{field} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field} must be an integer") from exc
        if parsed < 1 or parsed > maximum:
            raise ValidationError(f"{field} must be between 1 and {maximum}")
        return parsed

    @staticmethod
    def _optional_query(value: Any, field: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _sort(value: Any) -> str:
        if not isinstance(value, str) or not value:
            raise ValidationError("sort must be a string")
        descending = value.startswith("-")
        field = value[1:] if descending else value
        column = _SORT_COLUMNS.get(field)
        if column is None:
            raise ValidationError("sort must be one of name, start_at, end_at, created_at, updated_at")
        return f"{column} {'DESC' if descending else 'ASC'}, id ASC"
