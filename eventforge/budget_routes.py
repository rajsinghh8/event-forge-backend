"""HTTP blueprint for budget categories and their expenses."""
from flask import Blueprint, current_app, g, jsonify, request
from .security import require_auth
from .errors import ValidationError

budget_bp = Blueprint("budget", __name__)


def _service():
    services = current_app.extensions.get("services", {})
    service = services.get("budget") or services.get("budget_service")
    if service is None:
        raise RuntimeError("BudgetService has not been registered")
    return service


def _json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")
    return data


def _result(value, status=200):
    return jsonify(value), status


@budget_bp.get("/events/<event_id>/budget-categories")
@require_auth
def list_budget_categories(event_id):
    return _result(_service().list_categories(g.user_id, event_id, request.args))

@budget_bp.post("/events/<event_id>/budget-categories")
@require_auth
def create_budget_category(event_id):
    return _result(_service().create_category(g.user_id, event_id, _json()), 201)

@budget_bp.get("/events/<event_id>/budget-categories/<category_id>")
@require_auth
def get_budget_category(event_id, category_id):
    return _result(_service().get_category(g.user_id, event_id, category_id))

@budget_bp.patch("/events/<event_id>/budget-categories/<category_id>")
@require_auth
def update_budget_category(event_id, category_id):
    return _result(_service().update_category(g.user_id, event_id, category_id, _json()))

@budget_bp.delete("/events/<event_id>/budget-categories/<category_id>")
@require_auth
def delete_budget_category(event_id, category_id):
    _service().delete_category(g.user_id, event_id, category_id)
    return "", 204

@budget_bp.get("/events/<event_id>/budget-categories/<category_id>/expenses")
@require_auth
def list_expenses(event_id, category_id):
    return _result(_service().list_expenses(g.user_id, event_id, category_id, request.args))

@budget_bp.post("/events/<event_id>/budget-categories/<category_id>/expenses")
@require_auth
def create_expense(event_id, category_id):
    return _result(_service().create_expense(g.user_id, event_id, category_id, _json()), 201)

@budget_bp.get("/events/<event_id>/budget-categories/<category_id>/expenses/<expense_id>")
@require_auth
def get_expense(event_id, category_id, expense_id):
    return _result(_service().get_expense(g.user_id, event_id, category_id, expense_id))

@budget_bp.patch("/events/<event_id>/budget-categories/<category_id>/expenses/<expense_id>")
@require_auth
def update_expense(event_id, category_id, expense_id):
    return _result(_service().update_expense(g.user_id, event_id, category_id, expense_id, _json()))

@budget_bp.delete("/events/<event_id>/budget-categories/<category_id>/expenses/<expense_id>")
@require_auth
def delete_expense(event_id, category_id, expense_id):
    _service().delete_expense(g.user_id, event_id, category_id, expense_id)
    return "", 204
