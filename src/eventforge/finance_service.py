"""Application rules for event budget categories and expenses."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID, uuid4

from .finance_dto import (
    BudgetCategory,
    CategoryTotals,
    CreateBudgetCategory,
    CreateExpense,
    Expense,
    UpdateBudgetCategory,
)
from .finance_repository import (
    BudgetCeilingExceededError,
    CategoryInUseError,
    CategoryNotFoundError,
    FinanceRepository,
)


class AuditSink(Protocol):
    def record(self, *, actor_id: UUID, event_id: UUID, action: str, entity_type: str, entity_id: UUID, details: dict[str, str]) -> None: ...


class NotificationSink(Protocol):
    def notify_budget_warning(self, *, event_id: UUID, category_id: UUID, remaining: Decimal) -> None: ...


@dataclass(frozen=True, slots=True)
class CategoryWithTotals:
    category: BudgetCategory
    totals: CategoryTotals


class FinanceService:
    def __init__(self, repository: FinanceRepository, audit: AuditSink, notifications: NotificationSink) -> None:
        self._repository = repository
        self._audit = audit
        self._notifications = notifications

    def create_category(self, *, actor_id: UUID, event_id: UUID, command: CreateBudgetCategory) -> CategoryWithTotals:
        with self._repository.transaction():
            category = self._repository.create_category(event_id, command.name, command.budget_ceiling)
            totals = self._repository.category_totals(event_id, category.id)
        self._audit.record(actor_id=actor_id, event_id=event_id, action="budget_category.created", entity_type="budget_category", entity_id=category.id, details={"name": category.name})
        return CategoryWithTotals(category, totals)

    def get_category(self, *, event_id: UUID, category_id: UUID) -> CategoryWithTotals:
        with self._repository.transaction():
            category = self._require_category(event_id, category_id)
            return CategoryWithTotals(category, self._repository.category_totals(event_id, category_id))

    def update_category(self, *, actor_id: UUID, event_id: UUID, category_id: UUID, command: UpdateBudgetCategory) -> CategoryWithTotals:
        with self._repository.transaction():
            category = self._require_category(event_id, category_id, for_update=True)
            totals = self._repository.category_totals(event_id, category_id)
            ceiling = command.budget_ceiling if command.budget_ceiling is not None else category.budget_ceiling
            # A change must not turn already-recorded actual spending into overspend.
            if ceiling < totals.actual:
                raise BudgetCeilingExceededError("budget_ceiling cannot be lower than actual spending")
            changed = replace(category, name=command.name if command.name is not None else category.name, budget_ceiling=ceiling)
            changed = self._repository.update_category(changed)
            totals = self._repository.category_totals(event_id, category_id)
        self._audit.record(actor_id=actor_id, event_id=event_id, action="budget_category.updated", entity_type="budget_category", entity_id=category_id, details={"name": changed.name})
        return CategoryWithTotals(changed, totals)

    def delete_category(self, *, actor_id: UUID, event_id: UUID, category_id: UUID) -> None:
        with self._repository.transaction():
            self._require_category(event_id, category_id, for_update=True)
            if self._repository.category_expense_count(event_id, category_id):
                raise CategoryInUseError("cannot delete a category that has expenses")
            self._repository.delete_category(event_id, category_id)
        self._audit.record(actor_id=actor_id, event_id=event_id, action="budget_category.deleted", entity_type="budget_category", entity_id=category_id, details={})

    def create_expense(self, *, actor_id: UUID, event_id: UUID, command: CreateExpense) -> CategoryWithTotals:
        # Locking the category serializes concurrent totals checks and inserts.
        with self._repository.transaction():
            category = self._require_category(event_id, command.category_id, for_update=True)
            previous = self._repository.category_totals(event_id, category.id)
            projected_actual = previous.actual + command.amount
            if projected_actual > category.budget_ceiling:
                raise BudgetCeilingExceededError("expense would exceed the category budget ceiling")
            expense = Expense(id=uuid4(), event_id=event_id, category_id=category.id, amount=command.amount, occurred_on=command.occurred_on, description=command.description, created_at=datetime.now(timezone.utc))
            self._repository.create_expense(expense)
            totals = CategoryTotals.from_actual(category.id, category.budget_ceiling, projected_actual)
        self._audit.record(actor_id=actor_id, event_id=event_id, action="expense.created", entity_type="expense", entity_id=expense.id, details={"category_id": str(category.id), "amount": format(expense.amount, "f")})
        if totals.remaining == Decimal("0.00"):
            self._notifications.notify_budget_warning(event_id=event_id, category_id=category.id, remaining=totals.remaining)
        return CategoryWithTotals(category, totals)

    def list_expenses(self, *, event_id: UUID, category_id: UUID, offset: int, limit: int) -> tuple[list[Expense], int]:
        with self._repository.transaction():
            self._require_category(event_id, category_id)
            return self._repository.list_expenses(event_id, category_id, offset, limit)

    def _require_category(self, event_id: UUID, category_id: UUID, *, for_update: bool = False) -> BudgetCategory:
        category = self._repository.get_category(event_id, category_id, for_update=for_update)
        if category is None:
            raise CategoryNotFoundError("budget category was not found")
        return category
