"""Bottle route installer for the finance resource group.

The application supplies ``actor_id`` from its JWT authentication layer; this
module deliberately does not own global routing or authentication wiring.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from bottle import HTTPError, request, response

from .finance_dto import CreateBudgetCategory, CreateExpense, UpdateBudgetCategory, category_payload
from .finance_repository import BudgetCeilingExceededError, CategoryInUseError, CategoryNotFoundError
from .finance_service import FinanceService


def install_finance_routes(app, service: FinanceService, actor_id):
    """Install category and expense endpoints on an already configured Bottle app.

    ``actor_id`` is a zero-argument callable returning the authenticated UUID.
    """
    def body() -> dict:
        payload = request.json
        if not isinstance(payload, dict):
            raise HTTPError(400, "JSON object body is required")
        return payload

    def category_result(item):
        return category_payload(item.category, item.totals)

    @app.post("/events/<event_id>/budget-categories")
    def create_category(event_id):
        try:
            command = CreateBudgetCategory(**body())
            item = service.create_category(actor_id=actor_id(), event_id=UUID(event_id), command=command)
            response.status = 201
            return category_result(item)
        except ValueError as exc:
            raise HTTPError(400, str(exc))

    @app.get("/events/<event_id>/budget-categories/<category_id>")
    def get_category(event_id, category_id):
        try:
            return category_result(service.get_category(event_id=UUID(event_id), category_id=UUID(category_id)))
        except CategoryNotFoundError as exc:
            raise HTTPError(404, str(exc))
        except ValueError as exc:
            raise HTTPError(400, str(exc))

    @app.patch("/events/<event_id>/budget-categories/<category_id>")
    def update_category(event_id, category_id):
        try:
            item = service.update_category(actor_id=actor_id(), event_id=UUID(event_id), category_id=UUID(category_id), command=UpdateBudgetCategory(**body()))
            return category_result(item)
        except CategoryNotFoundError as exc:
            raise HTTPError(404, str(exc))
        except BudgetCeilingExceededError as exc:
            raise HTTPError(409, str(exc))
        except ValueError as exc:
            raise HTTPError(400, str(exc))

    @app.delete("/events/<event_id>/budget-categories/<category_id>")
    def delete_category(event_id, category_id):
        try:
            service.delete_category(actor_id=actor_id(), event_id=UUID(event_id), category_id=UUID(category_id))
            response.status = 204
            return ""
        except CategoryNotFoundError as exc:
            raise HTTPError(404, str(exc))
        except CategoryInUseError as exc:
            raise HTTPError(409, str(exc))

    @app.post("/events/<event_id>/budget-categories/<category_id>/expenses")
    def create_expense(event_id, category_id):
        try:
            payload = body()
            command = CreateExpense(category_id=UUID(category_id), amount=payload.get("amount"), occurred_on=date.fromisoformat(payload.get("occurred_on", "")), description=payload.get("description"))
            item = service.create_expense(actor_id=actor_id(), event_id=UUID(event_id), command=command)
            response.status = 201
            return category_result(item)
        except CategoryNotFoundError as exc:
            raise HTTPError(404, str(exc))
        except BudgetCeilingExceededError as exc:
            raise HTTPError(409, str(exc))
        except (TypeError, ValueError) as exc:
            raise HTTPError(400, str(exc))

    @app.get("/events/<event_id>/budget-categories/<category_id>/expenses")
    def list_expenses(event_id, category_id):
        try:
            page = max(1, int(request.query.get("page", "1")))
            page_size = min(100, max(1, int(request.query.get("page_size", "20"))))
            expenses, total = service.list_expenses(event_id=UUID(event_id), category_id=UUID(category_id), offset=(page - 1) * page_size, limit=page_size)
            return {"items": [{"id": str(x.id), "category_id": str(x.category_id), "amount": format(x.amount, "f"), "occurred_on": x.occurred_on.isoformat(), "description": x.description, "created_at": x.created_at.isoformat()} for x in expenses], "total": total, "page": page, "page_size": page_size}
        except CategoryNotFoundError as exc:
            raise HTTPError(404, str(exc))
        except ValueError as exc:
            raise HTTPError(400, str(exc))
