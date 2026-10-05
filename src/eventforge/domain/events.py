"""Core Event aggregate and calculations independent of Oracle or HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from .errors import ValidationError


class EventStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class Event:
    id: UUID
    owner_id: str
    name: str
    event_datetime: datetime
    venue: str | None
    capacity: int | None
    budget_limit: Decimal | None
    status: EventStatus
    description: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class EventAggregate:
    """Calculated event metrics.

    `actual_spend` and `attendee_count` are supplied by collaborating feature
    queries. Keeping the arithmetic here makes its boundary behaviour testable
    without a database.
    """

    event_id: UUID
    attendee_count: int
    remaining_capacity: int | None
    actual_spend: Decimal
    remaining_budget: Decimal | None


def calculate_event_aggregate(
    event: Event, *, attendee_count: int = 0, actual_spend: Decimal = Decimal("0")
) -> EventAggregate:
    if attendee_count < 0:
        raise ValidationError("attendee_count cannot be negative")
    if actual_spend < 0:
        raise ValidationError("actual_spend cannot be negative")
    if event.capacity is not None and attendee_count > event.capacity:
        # Data may be over capacity, but exposing a negative availability is
        # never useful to clients.
        remaining_capacity: int | None = 0
    elif event.capacity is None:
        remaining_capacity = None
    else:
        remaining_capacity = event.capacity - attendee_count

    return EventAggregate(
        event_id=event.id,
        attendee_count=attendee_count,
        remaining_capacity=remaining_capacity,
        actual_spend=actual_spend,
        remaining_budget=(None if event.budget_limit is None else event.budget_limit - actual_spend),
    )
