"""Application service for owner-scoped Event CRUD and activity auditing."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from .domain.errors import NotFoundError, ValidationError
from .domain.events import Event, EventAggregate, calculate_event_aggregate
from .event_dto import CreateEvent, EventFilters, OffsetEnvelope, OffsetPage, UpdateEvent
from .event_repository import EventRepository, OracleConnection


class TransactionManager(Protocol):
    """The context manager must commit only after its body completes normally."""
    def transaction(self) -> AbstractContextManager[OracleConnection]: ...


class TransactionalActivityAudit(Protocol):
    """Audit implementation must use the supplied connection, never open another.

    This is the transaction contract: event mutation and its audit record commit
    or roll back together in the transaction provided by ``TransactionManager``.
    """
    def record(self, connection: OracleConnection, *, owner_id: str, action: str,
               entity_type: str, entity_id: UUID, details: dict[str, Any]) -> None: ...


@dataclass(slots=True)
class EventService:
    repository: EventRepository
    transactions: TransactionManager
    audit: TransactionalActivityAudit

    @staticmethod
    def _owner(owner_id: str) -> str:
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValidationError("JWT user_id is required")
        return owner_id.strip()

    def create(self, *, owner_id: str, command: CreateEvent) -> Event:
        owner_id = self._owner(owner_id)
        event_id = uuid4()
        with self.transactions.transaction() as connection:
            event = self.repository.create(connection, event_id=event_id, owner_id=owner_id, command=command)
            self.audit.record(connection, owner_id=owner_id, action="EVENT_CREATED", entity_type="EVENT", entity_id=event.id,
                              details={"name": event.name, "status": event.status.value})
            return event

    def get(self, *, owner_id: str, event_id: UUID) -> Event:
        with self.transactions.transaction() as connection:
            event = self.repository.get_owned(connection, event_id=event_id, owner_id=self._owner(owner_id))
        if event is None:
            # Identical response for another user's ID and a nonexistent ID.
            raise NotFoundError("event not found")
        return event

    def list(self, *, owner_id: str, filters: EventFilters | None = None, page: OffsetPage | None = None) -> OffsetEnvelope[Event]:
        owner_id = self._owner(owner_id)
        filters, page = filters or EventFilters(), page or OffsetPage()
        with self.transactions.transaction() as connection:
            items, total = self.repository.list_owned(connection, owner_id=owner_id, filters=filters, page=page)
        return OffsetEnvelope.from_offset(items, total, page)

    def update(self, *, owner_id: str, event_id: UUID, command: UpdateEvent) -> Event:
        owner_id = self._owner(owner_id)
        with self.transactions.transaction() as connection:
            event = self.repository.update_owned(connection, event_id=event_id, owner_id=owner_id, command=command)
            if event is None:
                raise NotFoundError("event not found")
            self.audit.record(connection, owner_id=owner_id, action="EVENT_UPDATED", entity_type="EVENT", entity_id=event_id,
                              details={"changed_fields": sorted(self._changed_fields(command))})
            return event

    def delete(self, *, owner_id: str, event_id: UUID) -> None:
        owner_id = self._owner(owner_id)
        with self.transactions.transaction() as connection:
            if not self.repository.delete_owned(connection, event_id=event_id, owner_id=owner_id):
                raise NotFoundError("event not found")
            self.audit.record(connection, owner_id=owner_id, action="EVENT_DELETED", entity_type="EVENT", entity_id=event_id, details={})

    def aggregate(self, *, owner_id: str, event_id: UUID) -> EventAggregate:
        owner_id = self._owner(owner_id)
        with self.transactions.transaction() as connection:
            event = self.repository.get_owned(connection, event_id=event_id, owner_id=owner_id)
            inputs = self.repository.aggregate_inputs(connection, event_id=event_id, owner_id=owner_id)
        if event is None or inputs is None:
            raise NotFoundError("event not found")
        return calculate_event_aggregate(event, attendee_count=inputs[0], actual_spend=inputs[1])

    @staticmethod
    def _changed_fields(command: UpdateEvent) -> set[str]:
        fields = {"name", "event_datetime", "venue", "capacity", "budget_limit", "status", "description"}
        return {field for field in fields if getattr(command, field) is not None or field in command.clear}
