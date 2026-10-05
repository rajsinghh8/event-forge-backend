"""Budget and expense application service contracts for EventForge.

Persistence, audit storage, and notification delivery are deliberately kept behind
``BudgetRepository``.  This module contains no transport or SQL concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from uuid import uuid4

from eventforge.errors import ConflictError, NotFoundError, ValidationError


MoneyInput = Decimal | str | int | float
_MONEY_PLACES = Decimal("0.01")
_NINETY_PERCENT = Decimal("0.90")
_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class BudgetCategoryRecord:
    """Persistence-facing category shape used by the repository contract."""

    id: str
    event_id: str
    name: str
    planned_amount: Decimal
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ExpenseRecord:
    """Persistence-facing expense shape used by the repository contract."""

    id: str
    event_id: str
    category_id: str
    description: str
    actual_amount: Decimal
    incurred_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BudgetCategoryDTO:
    id: str
    event_id: str
    name: str
    planned_amount: str
    actual_amount: str
    remaining_amount: str
    spent_percent: str


@dataclass(frozen=True, slots=True)
class ExpenseDTO:
    id: str
    event_id: str
    category_id: str
    description: str
    actual_amount: str
    incurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class CategoryBudgetAggregateDTO:
    category: BudgetCategoryDTO
    expense_count: int


@dataclass(frozen=True, slots=True)
class BudgetAggregateDTO:
    event_id: str
    planned_amount: str
    actual_amount: str
    remaining_amount: str
    spent_percent: str
    categories: tuple[CategoryBudgetAggregateDTO, ...]


class BudgetRepository(Protocol):
    """Local dependency contract for budget persistence and side effects.

    ``notify_spending_threshold_once`` must be atomic: it records the threshold
    notification key and queues/delivers the notification only on its first call
    for that category and threshold.  That makes retries and concurrent writes
    deduplicated without requiring this service to know repository internals.
    """

    def get_category(self, event_id: str, category_id: str) -> BudgetCategoryRecord | None: ...
    def list_categories(self, event_id: str) -> list[BudgetCategoryRecord]: ...
    def insert_category(self, category: BudgetCategoryRecord) -> BudgetCategoryRecord: ...
    def update_category(self, category: BudgetCategoryRecord) -> BudgetCategoryRecord: ...
    def delete_category(self, event_id: str, category_id: str) -> None: ...

    def get_expense(self, event_id: str, expense_id: str) -> ExpenseRecord | None: ...
    def list_expenses(self, event_id: str, category_id: str | None = None) -> list[ExpenseRecord]: ...
    def insert_expense(self, expense: ExpenseRecord) -> ExpenseRecord: ...
    def update_expense(self, expense: ExpenseRecord) -> ExpenseRecord: ...
    def delete_expense(self, event_id: str, expense_id: str) -> None: ...

    def audit(
        self, *, event_id: str, actor_id: str, action: str, entity_type: str,
        entity_id: str, details: dict[str, str]
    ) -> None: ...

    def notify_spending_threshold_once(
        self, *, event_id: str, category_id: str, spent_amount: Decimal,
        planned_amount: Decimal, threshold: Decimal
    ) -> bool: ...


class BudgetResourceService:
    """Typed dependency-injected use cases for categories and expenses."""

    def __init__(self, repository: BudgetRepository) -> None:
        self._repository = repository

    # Category CRUD
    def create_category(
        self, event_id: str, actor_id: str, *, name: str, planned_amount: MoneyInput
    ) -> BudgetCategoryDTO:
        category = BudgetCategoryRecord(
            id=str(uuid4()), event_id=event_id, name=self._required_text(name, "name"),
            planned_amount=self._money(planned_amount, "planned_amount"),
        )
        created = self._repository.insert_category(category)
        self._audit(actor_id, "budget_category.created", created, {"planned_amount": self._decimal_text(created.planned_amount)})
        return self._category_dto(created, _ZERO)

    def get_category(self, event_id: str, category_id: str) -> BudgetCategoryDTO:
        category = self._category_or_404(event_id, category_id)
        return self._category_dto(category, self._spent(event_id, category_id))

    def list_categories(self, event_id: str) -> tuple[BudgetCategoryDTO, ...]:
        return tuple(self._category_dto(category, self._spent(event_id, category.id)) for category in self._repository.list_categories(event_id))

    def update_category(
        self, event_id: str, category_id: str, actor_id: str, *, name: str | None = None,
        planned_amount: MoneyInput | None = None,
    ) -> BudgetCategoryDTO:
        category = self._category_or_404(event_id, category_id)
        spent = self._spent(event_id, category_id)
        new_planned = category.planned_amount if planned_amount is None else self._money(planned_amount, "planned_amount")
        if new_planned < spent:
            raise ConflictError("planned_amount cannot be less than actual spending")
        updated = self._repository.update_category(replace(
            category,
            name=category.name if name is None else self._required_text(name, "name"),
            planned_amount=new_planned,
        ))
        self._audit(actor_id, "budget_category.updated", updated, {"planned_amount": self._decimal_text(updated.planned_amount)})
        self._notify_if_needed(updated, spent)
        return self._category_dto(updated, spent)

    def delete_category(self, event_id: str, category_id: str, actor_id: str) -> None:
        category = self._category_or_404(event_id, category_id)
        spent = self._spent(event_id, category_id)
        if spent > _ZERO:
            raise ConflictError("a category with recorded spending cannot be deleted")
        self._repository.delete_category(event_id, category_id)
        self._audit(actor_id, "budget_category.deleted", category, {})

    # Expense CRUD
    def create_expense(
        self, event_id: str, actor_id: str, *, category_id: str, description: str,
        actual_amount: MoneyInput, incurred_at: datetime | None = None,
    ) -> ExpenseDTO:
        category = self._category_or_404(event_id, category_id)
        amount = self._money(actual_amount, "actual_amount")
        new_spent = self._spent(event_id, category_id) + amount
        self._assert_within_plan(category, new_spent)
        created = self._repository.insert_expense(ExpenseRecord(
            id=str(uuid4()), event_id=event_id, category_id=category_id,
            description=self._required_text(description, "description"), actual_amount=amount,
            incurred_at=incurred_at,
        ))
        self._audit(actor_id, "expense.created", created, {"actual_amount": self._decimal_text(amount), "category_id": category_id})
        self._notify_if_needed(category, new_spent)
        return self._expense_dto(created)

    def get_expense(self, event_id: str, expense_id: str) -> ExpenseDTO:
        return self._expense_dto(self._expense_or_404(event_id, expense_id))

    def list_expenses(self, event_id: str, *, category_id: str | None = None) -> tuple[ExpenseDTO, ...]:
        if category_id is not None:
            self._category_or_404(event_id, category_id)
        return tuple(self._expense_dto(expense) for expense in self._repository.list_expenses(event_id, category_id))

    def update_expense(
        self, event_id: str, expense_id: str, actor_id: str, *, category_id: str | None = None,
        description: str | None = None, actual_amount: MoneyInput | None = None,
        incurred_at: datetime | None = None,
    ) -> ExpenseDTO:
        expense = self._expense_or_404(event_id, expense_id)
        target_category_id = expense.category_id if category_id is None else category_id
        target_category = self._category_or_404(event_id, target_category_id)
        amount = expense.actual_amount if actual_amount is None else self._money(actual_amount, "actual_amount")
        target_spent = self._spent(event_id, target_category_id, excluding_expense_id=expense_id) + amount
        self._assert_within_plan(target_category, target_spent)
        updated = self._repository.update_expense(replace(
            expense, category_id=target_category_id,
            description=expense.description if description is None else self._required_text(description, "description"),
            actual_amount=amount, incurred_at=expense.incurred_at if incurred_at is None else incurred_at,
        ))
        self._audit(actor_id, "expense.updated", updated, {"actual_amount": self._decimal_text(amount), "category_id": target_category_id})
        self._notify_if_needed(target_category, target_spent)
        return self._expense_dto(updated)

    def delete_expense(self, event_id: str, expense_id: str, actor_id: str) -> None:
        expense = self._expense_or_404(event_id, expense_id)
        self._repository.delete_expense(event_id, expense_id)
        self._audit(actor_id, "expense.deleted", expense, {"actual_amount": self._decimal_text(expense.actual_amount)})

    def get_budget_aggregate(self, event_id: str) -> BudgetAggregateDTO:
        aggregates: list[CategoryBudgetAggregateDTO] = []
        planned = _ZERO
        actual = _ZERO
        for category in self._repository.list_categories(event_id):
            expenses = self._repository.list_expenses(event_id, category.id)
            spent = sum((expense.actual_amount for expense in expenses), _ZERO)
            planned += category.planned_amount
            actual += spent
            aggregates.append(CategoryBudgetAggregateDTO(self._category_dto(category, spent), len(expenses)))
        return BudgetAggregateDTO(
            event_id=event_id, planned_amount=self._decimal_text(planned), actual_amount=self._decimal_text(actual),
            remaining_amount=self._decimal_text(planned - actual), spent_percent=self._percent(actual, planned),
            categories=tuple(aggregates),
        )

    def _category_or_404(self, event_id: str, category_id: str) -> BudgetCategoryRecord:
        category = self._repository.get_category(event_id, category_id)
        if category is None:
            raise NotFoundError("budget category was not found")
        return category

    def _expense_or_404(self, event_id: str, expense_id: str) -> ExpenseRecord:
        expense = self._repository.get_expense(event_id, expense_id)
        if expense is None:
            raise NotFoundError("expense was not found")
        return expense

    def _spent(self, event_id: str, category_id: str, *, excluding_expense_id: str | None = None) -> Decimal:
        return sum((expense.actual_amount for expense in self._repository.list_expenses(event_id, category_id) if expense.id != excluding_expense_id), _ZERO)

    def _assert_within_plan(self, category: BudgetCategoryRecord, spent: Decimal) -> None:
        if spent > category.planned_amount:
            raise ConflictError("actual spending cannot exceed planned_amount")

    def _notify_if_needed(self, category: BudgetCategoryRecord, spent: Decimal) -> None:
        if category.planned_amount > _ZERO and spent >= category.planned_amount * _NINETY_PERCENT:
            self._repository.notify_spending_threshold_once(
                event_id=category.event_id, category_id=category.id, spent_amount=spent,
                planned_amount=category.planned_amount, threshold=_NINETY_PERCENT,
            )

    def _audit(self, actor_id: str, action: str, record: BudgetCategoryRecord | ExpenseRecord, details: dict[str, str]) -> None:
        self._repository.audit(event_id=record.event_id, actor_id=actor_id, action=action,
                               entity_type="budget_category" if isinstance(record, BudgetCategoryRecord) else "expense",
                               entity_id=record.id, details=details)

    @staticmethod
    def _required_text(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(f"{field} is required")
        return value.strip()

    @staticmethod
    def _money(value: MoneyInput, field: str) -> Decimal:
        if isinstance(value, bool):
            raise ValidationError(f"{field} must be a decimal amount")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError(f"{field} must be a decimal amount") from None
        if not amount.is_finite() or amount < _ZERO or amount.as_tuple().exponent < -2:
            raise ValidationError(f"{field} must be a non-negative amount with at most two decimal places")
        return amount.quantize(_MONEY_PLACES)

    @staticmethod
    def _decimal_text(value: Decimal) -> str:
        return format(value.quantize(_MONEY_PLACES), "f")

    @classmethod
    def _percent(cls, actual: Decimal, planned: Decimal) -> str:
        if planned == _ZERO:
            return "0.00"
        return cls._decimal_text((actual / planned) * Decimal("100"))

    @classmethod
    def _category_dto(cls, category: BudgetCategoryRecord, spent: Decimal) -> BudgetCategoryDTO:
        return BudgetCategoryDTO(category.id, category.event_id, category.name,
                                 cls._decimal_text(category.planned_amount), cls._decimal_text(spent),
                                 cls._decimal_text(category.planned_amount - spent), cls._percent(spent, category.planned_amount))

    @classmethod
    def _expense_dto(cls, expense: ExpenseRecord) -> ExpenseDTO:
        return ExpenseDTO(expense.id, expense.event_id, expense.category_id, expense.description,
                          cls._decimal_text(expense.actual_amount), expense.incurred_at)
