"""Application service for event schedules, vendors, and vendor payments.

The repository supplied to this service owns persistence and owner-scoping.  All
money crossing this boundary is a :class:`~decimal.Decimal`; response DTOs use
fixed-point strings so JSON encoding never converts a monetary value to float.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import ContextManager, NotRequired, Protocol, TypedDict

from eventforge.errors import ConflictError, NotFoundError, ValidationError


class ScheduleItemInput(TypedDict):
    title: str
    start_at: datetime
    end_at: datetime
    description: NotRequired[str | None]


class VendorInput(TypedDict):
    name: str
    total_amount: Decimal | str
    contact_name: NotRequired[str | None]
    contact_email: NotRequired[str | None]


class VendorPaymentInput(TypedDict):
    amount: Decimal | str
    paid_on: date
    reference: NotRequired[str | None]


ScheduleItemDTO = dict[str, object]
VendorDTO = dict[str, object]
VendorPaymentDTO = dict[str, object]
Record = Mapping[str, object]


class OperationsRepository(Protocol):
    """Persistence contract required by :class:`OperationsResourceService`.

    Every getter is owner-scoped.  Implementations should return ``None`` for
    both absent and inaccessible resources, preserving the application's 404
    ownership policy.
    """

    def transaction(self) -> ContextManager[None]: ...

    def get_event(self, user_id: int, event_id: int) -> Record | None: ...

    def list_schedule_items(self, user_id: int, event_id: int) -> Sequence[Record]: ...

    def get_schedule_item(
        self, user_id: int, event_id: int, schedule_item_id: int
    ) -> Record | None: ...

    def create_schedule_item(self, event_id: int, values: ScheduleItemInput) -> Record: ...

    def update_schedule_item(
        self, event_id: int, schedule_item_id: int, values: ScheduleItemInput
    ) -> Record: ...

    def delete_schedule_item(self, event_id: int, schedule_item_id: int) -> None: ...

    def list_vendors(self, user_id: int, event_id: int) -> Sequence[Record]: ...

    def get_vendor(self, user_id: int, event_id: int, vendor_id: int) -> Record | None: ...

    def create_vendor(self, event_id: int, values: VendorInput) -> Record: ...

    def update_vendor(self, event_id: int, vendor_id: int, values: VendorInput) -> Record: ...

    def delete_vendor(self, event_id: int, vendor_id: int) -> None: ...

    def vendor_paid_total(self, vendor_id: int, *, exclude_payment_id: int | None = None) -> Decimal: ...

    def list_vendor_payments(
        self, user_id: int, event_id: int, vendor_id: int
    ) -> Sequence[Record]: ...

    def get_vendor_payment(
        self, user_id: int, event_id: int, vendor_id: int, payment_id: int
    ) -> Record | None: ...

    def create_vendor_payment(self, vendor_id: int, values: VendorPaymentInput) -> Record: ...

    def update_vendor_payment(
        self, vendor_id: int, payment_id: int, values: VendorPaymentInput
    ) -> Record: ...

    def delete_vendor_payment(self, vendor_id: int, payment_id: int) -> None: ...

    def record_audit(
        self,
        *,
        user_id: int,
        event_id: int,
        entity_type: str,
        entity_id: int,
        action: str,
        details: Mapping[str, object] | None = None,
    ) -> None: ...


@dataclass(slots=True)
class OperationsResourceService:
    """Owner-scoped schedule, vendor, and payment business operations."""

    repository: OperationsRepository

    # Schedule item contracts -------------------------------------------------
    def list_schedule_items(self, user_id: int, event_id: int) -> list[ScheduleItemDTO]:
        self._require_event(user_id, event_id)
        return [dict(item) for item in self.repository.list_schedule_items(user_id, event_id)]

    def get_schedule_item(self, user_id: int, event_id: int, schedule_item_id: int) -> ScheduleItemDTO:
        return dict(self._require_schedule_item(user_id, event_id, schedule_item_id))

    def create_schedule_item(
        self, user_id: int, event_id: int, values: ScheduleItemInput
    ) -> ScheduleItemDTO:
        payload = self._schedule_payload(values)
        with self.repository.transaction():
            self._require_event(user_id, event_id)
            self._ensure_no_schedule_overlap(user_id, event_id, payload["start_at"], payload["end_at"])
            item = self.repository.create_schedule_item(event_id, payload)
            self._audit(user_id, event_id, "schedule_item", item, "create")
        return dict(item)

    def update_schedule_item(
        self, user_id: int, event_id: int, schedule_item_id: int, values: ScheduleItemInput
    ) -> ScheduleItemDTO:
        payload = self._schedule_payload(values)
        with self.repository.transaction():
            self._require_schedule_item(user_id, event_id, schedule_item_id)
            self._ensure_no_schedule_overlap(
                user_id, event_id, payload["start_at"], payload["end_at"], exclude_id=schedule_item_id
            )
            item = self.repository.update_schedule_item(event_id, schedule_item_id, payload)
            self._audit(user_id, event_id, "schedule_item", item, "update")
        return dict(item)

    def delete_schedule_item(self, user_id: int, event_id: int, schedule_item_id: int) -> None:
        with self.repository.transaction():
            item = self._require_schedule_item(user_id, event_id, schedule_item_id)
            self.repository.delete_schedule_item(event_id, schedule_item_id)
            self._audit(user_id, event_id, "schedule_item", item, "delete")

    # Vendor contracts --------------------------------------------------------
    def list_vendors(self, user_id: int, event_id: int) -> list[VendorDTO]:
        self._require_event(user_id, event_id)
        return [self._vendor_dto(vendor) for vendor in self.repository.list_vendors(user_id, event_id)]

    def get_vendor(self, user_id: int, event_id: int, vendor_id: int) -> VendorDTO:
        return self._vendor_dto(self._require_vendor(user_id, event_id, vendor_id))

    def create_vendor(self, user_id: int, event_id: int, values: VendorInput) -> VendorDTO:
        payload = self._vendor_payload(values)
        with self.repository.transaction():
            self._require_event(user_id, event_id)
            vendor = self.repository.create_vendor(event_id, payload)
            self._audit(user_id, event_id, "vendor", vendor, "create")
        return self._vendor_dto(vendor)

    def update_vendor(
        self, user_id: int, event_id: int, vendor_id: int, values: VendorInput
    ) -> VendorDTO:
        payload = self._vendor_payload(values)
        with self.repository.transaction():
            vendor = self._require_vendor(user_id, event_id, vendor_id)
            paid = self.repository.vendor_paid_total(vendor_id)
            if payload["total_amount"] < paid:
                raise ConflictError("Vendor total cannot be lower than payments already made")
            updated = self.repository.update_vendor(event_id, vendor_id, payload)
            self._audit(user_id, event_id, "vendor", updated, "update")
        return self._vendor_dto(updated)

    def delete_vendor(self, user_id: int, event_id: int, vendor_id: int) -> None:
        with self.repository.transaction():
            vendor = self._require_vendor(user_id, event_id, vendor_id)
            self.repository.delete_vendor(event_id, vendor_id)
            self._audit(user_id, event_id, "vendor", vendor, "delete")

    # Vendor payment contracts ------------------------------------------------
    def list_vendor_payments(self, user_id: int, event_id: int, vendor_id: int) -> list[VendorPaymentDTO]:
        self._require_vendor(user_id, event_id, vendor_id)
        return [self._payment_dto(payment) for payment in self.repository.list_vendor_payments(user_id, event_id, vendor_id)]

    def get_vendor_payment(
        self, user_id: int, event_id: int, vendor_id: int, payment_id: int
    ) -> VendorPaymentDTO:
        return self._payment_dto(self._require_payment(user_id, event_id, vendor_id, payment_id))

    def create_vendor_payment(
        self, user_id: int, event_id: int, vendor_id: int, values: VendorPaymentInput
    ) -> VendorPaymentDTO:
        payload = self._payment_payload(values)
        with self.repository.transaction():
            vendor = self._require_vendor(user_id, event_id, vendor_id)
            self._ensure_payment_within_total(vendor, vendor_id, payload["amount"])
            payment = self.repository.create_vendor_payment(vendor_id, payload)
            self._audit(user_id, event_id, "vendor_payment", payment, "create")
        return self._payment_dto(payment)

    def update_vendor_payment(
        self, user_id: int, event_id: int, vendor_id: int, payment_id: int, values: VendorPaymentInput
    ) -> VendorPaymentDTO:
        payload = self._payment_payload(values)
        with self.repository.transaction():
            vendor = self._require_vendor(user_id, event_id, vendor_id)
            self._require_payment(user_id, event_id, vendor_id, payment_id)
            self._ensure_payment_within_total(vendor, vendor_id, payload["amount"], exclude_payment_id=payment_id)
            payment = self.repository.update_vendor_payment(vendor_id, payment_id, payload)
            self._audit(user_id, event_id, "vendor_payment", payment, "update")
        return self._payment_dto(payment)

    def delete_vendor_payment(self, user_id: int, event_id: int, vendor_id: int, payment_id: int) -> None:
        with self.repository.transaction():
            payment = self._require_payment(user_id, event_id, vendor_id, payment_id)
            self.repository.delete_vendor_payment(vendor_id, payment_id)
            self._audit(user_id, event_id, "vendor_payment", payment, "delete")

    # Validation and serialization -------------------------------------------
    def _require_event(self, user_id: int, event_id: int) -> Record:
        event = self.repository.get_event(user_id, event_id)
        if event is None:
            raise NotFoundError("Event not found")
        return event

    def _require_schedule_item(self, user_id: int, event_id: int, schedule_item_id: int) -> Record:
        item = self.repository.get_schedule_item(user_id, event_id, schedule_item_id)
        if item is None:
            raise NotFoundError("Schedule item not found")
        return item

    def _require_vendor(self, user_id: int, event_id: int, vendor_id: int) -> Record:
        vendor = self.repository.get_vendor(user_id, event_id, vendor_id)
        if vendor is None:
            raise NotFoundError("Vendor not found")
        return vendor

    def _require_payment(self, user_id: int, event_id: int, vendor_id: int, payment_id: int) -> Record:
        payment = self.repository.get_vendor_payment(user_id, event_id, vendor_id, payment_id)
        if payment is None:
            raise NotFoundError("Vendor payment not found")
        return payment

    def _schedule_payload(self, values: ScheduleItemInput) -> ScheduleItemInput:
        start_at, end_at = values["start_at"], values["end_at"]
        if not isinstance(start_at, datetime) or not isinstance(end_at, datetime):
            raise ValidationError("Schedule start_at and end_at must be datetimes")
        if end_at <= start_at:
            raise ValidationError("Schedule end_at must be after start_at")
        return dict(values)  # type: ignore[return-value]

    def _vendor_payload(self, values: VendorInput) -> VendorInput:
        payload = dict(values)
        payload["total_amount"] = self._money(values["total_amount"], field="total_amount", allow_zero=True)
        return payload  # type: ignore[return-value]

    def _payment_payload(self, values: VendorPaymentInput) -> VendorPaymentInput:
        if not isinstance(values["paid_on"], date):
            raise ValidationError("Payment paid_on must be a date")
        payload = dict(values)
        payload["amount"] = self._money(values["amount"], field="amount", allow_zero=False)
        return payload  # type: ignore[return-value]

    def _ensure_no_schedule_overlap(
        self, user_id: int, event_id: int, start_at: datetime, end_at: datetime, *, exclude_id: int | None = None
    ) -> None:
        for item in self.repository.list_schedule_items(user_id, event_id):
            item_id = item.get("id")
            if item_id == exclude_id:
                continue
            other_start, other_end = item.get("start_at"), item.get("end_at")
            if isinstance(other_start, datetime) and isinstance(other_end, datetime) and start_at < other_end and end_at > other_start:
                raise ConflictError("Schedule item overlaps an existing schedule item")

    def _ensure_payment_within_total(
        self, vendor: Record, vendor_id: int, amount: Decimal, *, exclude_payment_id: int | None = None
    ) -> None:
        total = self._money(vendor["total_amount"], field="total_amount", allow_zero=True)
        paid = self.repository.vendor_paid_total(vendor_id, exclude_payment_id=exclude_payment_id)
        if paid + amount > total:
            raise ConflictError("Vendor payments cannot exceed the vendor total")

    def _vendor_dto(self, vendor: Record) -> VendorDTO:
        total = self._money(vendor["total_amount"], field="total_amount", allow_zero=True)
        vendor_id = vendor.get("id")
        if not isinstance(vendor_id, int):
            raise ValidationError("Vendor record has no integer id")
        paid = self.repository.vendor_paid_total(vendor_id)
        result = dict(vendor)
        result["total_amount"] = self._decimal_string(total)
        result["totalPaid"] = self._decimal_string(paid)
        result["outstanding"] = self._decimal_string(total - paid)
        return result

    def _payment_dto(self, payment: Record) -> VendorPaymentDTO:
        result = dict(payment)
        result["amount"] = self._decimal_string(self._money(payment["amount"], field="amount", allow_zero=False))
        return result

    def _audit(self, user_id: int, event_id: int, entity_type: str, entity: Record, action: str) -> None:
        entity_id = entity.get("id")
        if not isinstance(entity_id, int):
            raise ValidationError(f"{entity_type} record has no integer id")
        self.repository.record_audit(
            user_id=user_id, event_id=event_id, entity_type=entity_type,
            entity_id=entity_id, action=action,
        )

    @staticmethod
    def _money(value: object, *, field: str, allow_zero: bool) -> Decimal:
        if isinstance(value, bool) or isinstance(value, float):
            raise ValidationError(f"{field} must be a decimal string or Decimal, never a float")
        try:
            amount = value if isinstance(value, Decimal) else Decimal(value) if isinstance(value, str) else None
        except InvalidOperation:
            amount = None
        if amount is None or not amount.is_finite() or amount < 0 or (not allow_zero and amount == 0):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValidationError(f"{field} must be a finite {qualifier} decimal")
        return amount

    @staticmethod
    def _decimal_string(value: Decimal) -> str:
        return format(value, "f")
