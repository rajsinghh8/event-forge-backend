"""Repository contracts and direct Oracle implementation for finance."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Iterator, Protocol
from uuid import UUID, uuid4

from .domain.errors import ConflictError, NotFoundError
from .finance_dto import BudgetCategory, CategoryTotals, Expense, money


class CategoryNotFoundError(NotFoundError):
    pass


class CategoryInUseError(ConflictError):
    pass


class BudgetCeilingExceededError(ConflictError):
    pass


class FinanceRepository(Protocol):
    @contextmanager
    def transaction(self) -> Iterator["FinanceRepository"]: ...

    def create_category(self, event_id: UUID, name: str, budget_ceiling: Decimal) -> BudgetCategory: ...
    def get_category(self, event_id: UUID, category_id: UUID, *, for_update: bool = False) -> BudgetCategory | None: ...
    def update_category(self, category: BudgetCategory) -> BudgetCategory: ...
    def delete_category(self, event_id: UUID, category_id: UUID) -> bool: ...
    def category_expense_count(self, event_id: UUID, category_id: UUID) -> int: ...
    def category_totals(self, event_id: UUID, category_id: UUID) -> CategoryTotals: ...
    def create_expense(self, expense: Expense) -> Expense: ...
    def list_expenses(self, event_id: UUID, category_id: UUID, offset: int, limit: int) -> tuple[list[Expense], int]: ...


class OracleFinanceRepository:
    """Direct python-oracledb repository using only named bind parameters.

    The service locks a category before reading totals and adding an expense;
    this makes the ceiling check correct under concurrent expense requests.
    """

    INSERT_CATEGORY = """
        INSERT INTO budget_categories (id, event_id, name, budget_ceiling, created_at, updated_at)
        VALUES (:id, :event_id, :name, :budget_ceiling, SYSTIMESTAMP, SYSTIMESTAMP)
    """
    SELECT_CATEGORY = """
        SELECT id, event_id, name, budget_ceiling, created_at, updated_at
          FROM budget_categories
         WHERE id = :category_id AND event_id = :event_id
    """
    UPDATE_CATEGORY = """
        UPDATE budget_categories
           SET name = :name, budget_ceiling = :budget_ceiling, updated_at = SYSTIMESTAMP
         WHERE id = :category_id AND event_id = :event_id
    """
    COUNT_EXPENSES = """
        SELECT COUNT(*) FROM expenses WHERE event_id = :event_id AND category_id = :category_id
    """
    TOTALS = """
        SELECT NVL(SUM(amount), 0) FROM expenses WHERE event_id = :event_id AND category_id = :category_id
    """
    DELETE_CATEGORY = """
        DELETE FROM budget_categories WHERE id = :category_id AND event_id = :event_id
    """
    INSERT_EXPENSE = """
        INSERT INTO expenses (id, event_id, category_id, amount, occurred_on, description, created_at)
        VALUES (:id, :event_id, :category_id, :amount, :occurred_on, :description, SYSTIMESTAMP)
    """
    LIST_EXPENSES = """
        SELECT id, event_id, category_id, amount, occurred_on, description, created_at,
               COUNT(*) OVER () AS total_count
          FROM expenses
         WHERE event_id = :event_id AND category_id = :category_id
         ORDER BY occurred_on DESC, created_at DESC
         OFFSET :offset ROWS FETCH NEXT :limit ROWS ONLY
    """

    def __init__(self, connection_factory: Callable[[], object]) -> None:
        self._connection_factory = connection_factory
        self._connection: object | None = None

    @contextmanager
    def transaction(self) -> Iterator["OracleFinanceRepository"]:
        if self._connection is not None:
            yield self
            return
        connection = self._connection_factory()
        self._connection = connection
        try:
            yield self
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._connection = None
            connection.close()

    def _cursor(self):
        if self._connection is None:
            raise RuntimeError("finance repository operation requires transaction()")
        return self._connection.cursor()

    @staticmethod
    def _category(row: tuple) -> BudgetCategory:
        return BudgetCategory(id=UUID(str(row[0])), event_id=UUID(str(row[1])), name=row[2], budget_ceiling=money(row[3]), created_at=row[4], updated_at=row[5])

    @staticmethod
    def _expense(row: tuple) -> Expense:
        return Expense(id=UUID(str(row[0])), event_id=UUID(str(row[1])), category_id=UUID(str(row[2])), amount=money(row[3]), occurred_on=row[4], description=row[5], created_at=row[6])

    def create_category(self, event_id: UUID, name: str, budget_ceiling: Decimal) -> BudgetCategory:
        category_id = uuid4()
        with self._cursor() as cursor:
            cursor.execute(self.INSERT_CATEGORY, id=str(category_id), event_id=str(event_id), name=name, budget_ceiling=budget_ceiling)
        return self.get_category(event_id, category_id)  # type: ignore[return-value]

    def get_category(self, event_id: UUID, category_id: UUID, *, for_update: bool = False) -> BudgetCategory | None:
        sql = self.SELECT_CATEGORY + (" FOR UPDATE" if for_update else "")
        with self._cursor() as cursor:
            cursor.execute(sql, event_id=str(event_id), category_id=str(category_id))
            row = cursor.fetchone()
        return self._category(row) if row else None

    def update_category(self, category: BudgetCategory) -> BudgetCategory:
        with self._cursor() as cursor:
            cursor.execute(self.UPDATE_CATEGORY, event_id=str(category.event_id), category_id=str(category.id), name=category.name, budget_ceiling=category.budget_ceiling)
        return self.get_category(category.event_id, category.id)  # type: ignore[return-value]

    def delete_category(self, event_id: UUID, category_id: UUID) -> bool:
        with self._cursor() as cursor:
            cursor.execute(self.DELETE_CATEGORY, event_id=str(event_id), category_id=str(category_id))
            return cursor.rowcount == 1

    def category_expense_count(self, event_id: UUID, category_id: UUID) -> int:
        with self._cursor() as cursor:
            cursor.execute(self.COUNT_EXPENSES, event_id=str(event_id), category_id=str(category_id))
            return int(cursor.fetchone()[0])

    def category_totals(self, event_id: UUID, category_id: UUID) -> CategoryTotals:
        category = self.get_category(event_id, category_id)
        if category is None:
            raise CategoryNotFoundError("budget category was not found")
        with self._cursor() as cursor:
            cursor.execute(self.TOTALS, event_id=str(event_id), category_id=str(category_id))
            actual = money(cursor.fetchone()[0])
        return CategoryTotals.from_actual(category_id, category.budget_ceiling, actual)

    def create_expense(self, expense: Expense) -> Expense:
        with self._cursor() as cursor:
            cursor.execute(self.INSERT_EXPENSE, id=str(expense.id), event_id=str(expense.event_id), category_id=str(expense.category_id), amount=expense.amount, occurred_on=expense.occurred_on, description=expense.description)
        return expense

    def list_expenses(self, event_id: UUID, category_id: UUID, offset: int, limit: int) -> tuple[list[Expense], int]:
        with self._cursor() as cursor:
            cursor.execute(self.LIST_EXPENSES, event_id=str(event_id), category_id=str(category_id), offset=offset, limit=limit)
            rows = cursor.fetchall()
        return [self._expense(row) for row in rows], (int(rows[0][7]) if rows else 0)
