"""Request, filter, and response DTOs for the Event core resource."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Generic, Mapping, Sequence, TypeVar
from uuid import UUID

from .domain.errors import ValidationError
from .domain.events import Event, EventAggregate, EventStatus

MAX_PAGE_SIZE = 100
T = TypeVar("T")


def _optional_text(value: str | None, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text")
    value = value.strip()
    if len(value) > maximum:
        raise ValidationError(f"{field} must be at most {maximum} characters")
    return value or None


def _required_text(value: str, field: str, maximum: int) -> str:
    result = _optional_text(value, field, maximum)
    if result is None:
        raise ValidationError(f"{field} is required")
    return result


def _budget(value: Decimal | str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("budget_limit must be a decimal number") from exc
    if not result.is_finite() or result < 0:
        raise ValidationError("budget_limit must be a non-negative finite decimal")
    return result.quantize(Decimal("0.01"))


def _capacity(value: int | None) -> int | None:
    if value is None:
        return None
    # bool is technically an int but must not silently mean one seat.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError("capacity must be a non-negative integer")
    return value


def _status(value: EventStatus | str) -> EventStatus:
    try:
        return EventStatus(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in EventStatus)
        raise ValidationError(f"status must be one of: {allowed}") from exc


@dataclass(frozen=True, slots=True)
class CreateEvent:
    name: str
    event_datetime: datetime
    venue: str | None = None
    capacity: int | None = None
    budget_limit: Decimal | str | int | float | None = None
    status: EventStatus | str = EventStatus.DRAFT
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required_text(self.name, "name", 160))
        if not isinstance(self.event_datetime, datetime):
            raise ValidationError("event_datetime must be a datetime")
        object.__setattr__(self, "venue", _optional_text(self.venue, "venue", 240))
        object.__setattr__(self, "capacity", _capacity(self.capacity))
        object.__setattr__(self, "budget_limit", _budget(self.budget_limit))
        object.__setattr__(self, "status", _status(self.status))
        object.__setattr__(self, "description", _optional_text(self.description, "description", 4000))


@dataclass(frozen=True, slots=True)
class UpdateEvent:
    name: str | None = None
    event_datetime: datetime | None = None
    venue: str | None = None
    capacity: int | None = None
    budget_limit: Decimal | str | int | float | None = None
    status: EventStatus | str | None = None
    description: str | None = None
    # REST callers need an explicit way to clear nullable fields. Fields in
    # this set are emitted as NULL binds rather than treated as omitted.
    clear: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        valid = {"venue", "capacity", "budget_limit", "description"}
        if not self.clear <= valid:
            raise ValidationError("clear contains a non-nullable or unknown event field")
        supplied = any(value is not None for value in (
            self.name, self.event_datetime, self.venue, self.capacity,
            self.budget_limit, self.status, self.description,
        )) or bool(self.clear)
        if not supplied:
            raise ValidationError("at least one event field is required")
        if self.name is not None:
            object.__setattr__(self, "name", _required_text(self.name, "name", 160))
        if self.event_datetime is not None and not isinstance(self.event_datetime, datetime):
            raise ValidationError("event_datetime must be a datetime")
        if self.venue is not None:
            object.__setattr__(self, "venue", _optional_text(self.venue, "venue", 240))
        if self.capacity is not None:
            object.__setattr__(self, "capacity", _capacity(self.capacity))
        if self.budget_limit is not None:
            object.__setattr__(self, "budget_limit", _budget(self.budget_limit))
        if self.status is not None:
            object.__setattr__(self, "status", _status(self.status))
        if self.description is not None:
            object.__setattr__(self, "description", _optional_text(self.description, "description", 4000))


@dataclass(frozen=True, slots=True)
class OffsetPage:
    offset: int = 0
    page_size: int = 20

    def __post_init__(self) -> None:
        if isinstance(self.offset, bool) or not isinstance(self.offset, int) or self.offset < 0:
            raise ValidationError("offset must be a non-negative integer")
        if isinstance(self.page_size, bool) or not isinstance(self.page_size, int) or not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise ValidationError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")


@dataclass(frozen=True, slots=True)
class EventFilters:
    status: EventStatus | str | None = None
    search: str | None = None
    starts_from: datetime | None = None
    starts_to: datetime | None = None

    def __post_init__(self) -> None:
        if self.status is not None:
            object.__setattr__(self, "status", _status(self.status))
        if self.search is not None:
            text = _required_text(self.search, "search", 160)
            object.__setattr__(self, "search", text)
        if self.starts_from is not None and not isinstance(self.starts_from, datetime):
            raise ValidationError("starts_from must be a datetime")
        if self.starts_to is not None and not isinstance(self.starts_to, datetime):
            raise ValidationError("starts_to must be a datetime")
        if self.starts_from and self.starts_to and self.starts_from > self.starts_to:
            raise ValidationError("starts_from must not be after starts_to")


@dataclass(frozen=True, slots=True)
class OffsetEnvelope(Generic[T]):
    items: Sequence[T]
    total: int
    page: int
    page_size: int

    @classmethod
    def from_offset(cls, items: Sequence[T], total: int, request: OffsetPage) -> "OffsetEnvelope[T]":
        if total < 0:
            raise ValidationError("total cannot be negative")
        return cls(items=items, total=total, page=(request.offset // request.page_size) + 1, page_size=request.page_size)


def event_payload(event: Event, aggregate: EventAggregate | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": str(event.id), "name": event.name, "event_datetime": event.event_datetime.isoformat(),
        "venue": event.venue, "capacity": event.capacity,
        "budget_limit": None if event.budget_limit is None else format(event.budget_limit, "f"),
        "status": event.status.value, "description": event.description,
        "created_at": event.created_at.isoformat(), "updated_at": event.updated_at.isoformat(),
    }
    if aggregate is not None:
        result["aggregate"] = {
            "attendee_count": aggregate.attendee_count,
            "remaining_capacity": aggregate.remaining_capacity,
            "actual_spend": format(aggregate.actual_spend, "f"),
            "remaining_budget": None if aggregate.remaining_budget is None else format(aggregate.remaining_budget, "f"),
        }
    return result
