"""Decimal-safe data transfer objects for the finance resource group."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from .domain.errors import ValidationError

MONEY_QUANTUM = Decimal("0.01")


class FinanceValidationError(ValidationError, ValueError):
    """Raised when a finance request contains invalid user supplied data."""


def money(value: Decimal | str | int | float) -> Decimal:
    """Convert a JSON-like money value to a finite, two-decimal Decimal.

    Floats are converted through their string form so binary float artefacts never
    enter calculations or Oracle bind values.
    """
    try:
        result = Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise FinanceValidationError("amount must be a decimal number") from exc
    if not result.is_finite():
        raise FinanceValidationError("amount must be finite")
    return result


def positive_money(value: Decimal | str | int | float, field: str = "amount") -> Decimal:
    result = money(value)
    if result <= Decimal("0"):
        raise FinanceValidationError(f"{field} must be greater than zero")
    return result


@dataclass(frozen=True, slots=True)
class CreateBudgetCategory:
    name: str
    budget_ceiling: Decimal

    def __post_init__(self) -> None:
        clean_name = self.name.strip()
        if not clean_name:
            raise FinanceValidationError("name is required")
        if len(clean_name) > 120:
            raise FinanceValidationError("name must be at most 120 characters")
        object.__setattr__(self, "name", clean_name)
        object.__setattr__(self, "budget_ceiling", positive_money(self.budget_ceiling, "budget_ceiling"))


@dataclass(frozen=True, slots=True)
class UpdateBudgetCategory:
    name: str | None = None
    budget_ceiling: Decimal | None = None

    def __post_init__(self) -> None:
        if self.name is None and self.budget_ceiling is None:
            raise FinanceValidationError("provide a name or budget_ceiling")
        if self.name is not None:
            clean_name = self.name.strip()
            if not clean_name or len(clean_name) > 120:
                raise FinanceValidationError("name must contain 1 to 120 characters")
            object.__setattr__(self, "name", clean_name)
        if self.budget_ceiling is not None:
            object.__setattr__(self, "budget_ceiling", positive_money(self.budget_ceiling, "budget_ceiling"))


@dataclass(frozen=True, slots=True)
class CreateExpense:
    category_id: UUID
    amount: Decimal
    occurred_on: date
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", positive_money(self.amount))
        if not isinstance(self.occurred_on, date):
            raise FinanceValidationError("occurred_on must be an ISO date")
        if self.description is not None:
            clean = self.description.strip()
            if len(clean) > 500:
                raise FinanceValidationError("description must be at most 500 characters")
            object.__setattr__(self, "description", clean or None)


@dataclass(frozen=True, slots=True)
class BudgetCategory:
    id: UUID
    event_id: UUID
    name: str
    budget_ceiling: Decimal
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Expense:
    id: UUID
    event_id: UUID
    category_id: UUID
    amount: Decimal
    occurred_on: date
    description: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CategoryTotals:
    category_id: UUID
    planned: Decimal
    actual: Decimal
    remaining: Decimal

    @classmethod
    def from_actual(cls, category_id: UUID, ceiling: Decimal, actual: Decimal) -> "CategoryTotals":
        planned = money(ceiling)
        actual = money(actual)
        return cls(category_id=category_id, planned=planned, actual=actual, remaining=planned - actual)


def category_payload(category: BudgetCategory, totals: CategoryTotals) -> dict[str, Any]:
    """JSON-safe response representation; decimals are never coerced to float."""
    return {
        "id": str(category.id),
        "event_id": str(category.event_id),
        "name": category.name,
        "budget_ceiling": format(category.budget_ceiling, "f"),
        "planned": format(totals.planned, "f"),
        "actual": format(totals.actual, "f"),
        "remaining": format(totals.remaining, "f"),
        "created_at": category.created_at.isoformat(),
        "updated_at": category.updated_at.isoformat(),
    }
