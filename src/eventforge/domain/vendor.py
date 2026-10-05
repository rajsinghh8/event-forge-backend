"""Vendor and payment aggregates."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .errors import ValidationError


def positive_amount(value: Decimal | str | int | float, field: str) -> Decimal:
    """Normalize a money input and enforce the positive-money invariant."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError(f"{field} must be a decimal amount") from exc
    if not amount.is_finite() or amount <= Decimal("0"):
        raise ValidationError(f"{field} must be positive")
    return amount


@dataclass(frozen=True, slots=True)
class Vendor:
    id: str
    event_id: str
    name: str
    cost: Decimal
    service_description: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValidationError("event_id is required")
        if not self.name or not self.name.strip():
            raise ValidationError("vendor name is required")
        object.__setattr__(self, "cost", positive_amount(self.cost, "vendor cost"))


@dataclass(frozen=True, slots=True)
class Payment:
    id: str
    vendor_id: str
    amount: Decimal
    paid_at: datetime
    reference: str | None = None

    def __post_init__(self) -> None:
        if not self.vendor_id:
            raise ValidationError("vendor_id is required")
        object.__setattr__(self, "amount", positive_amount(self.amount, "payment amount"))
