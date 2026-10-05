from types import SimpleNamespace

import jwt
from flask import Flask

from eventforge.budget_routes import budget_bp
from eventforge.errors import AuthenticationError


class BudgetServiceStub:
    def list_categories(self, owner_id, event_id, query):
        assert owner_id == "user-1"
        assert event_id == "event-1"
        return {"items": [], "total": 0, "page": 1, "size": 20}


def _client():
    app = Flask(__name__)
    app.extensions["settings"] = SimpleNamespace(jwt_secret="test-secret", jwt_algorithm="HS256")
    app.extensions["services"] = {"budget": BudgetServiceStub()}
    @app.errorhandler(AuthenticationError)
    def authentication_error(error):
        return {"message": error.message}, 401
    app.register_blueprint(budget_bp)
    return app.test_client()


def _headers():
    token = jwt.encode({"sub": "user-1"}, "test-secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_budget_category_list_requires_jwt_and_uses_authenticated_owner():
    client = _client()
    path = "/events/event-1/budget-categories"
    assert client.get(path).status_code == 401
    response = client.get(path, headers=_headers())
    assert response.status_code == 200
    assert response.get_json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_every_budget_and_expense_route_is_wrapped_by_require_auth():
    client = _client()
    protected = [
        rule for rule in client.application.url_map.iter_rules()
        if rule.endpoint.startswith("budget.")
    ]
    assert len(protected) == 10
    for rule in protected:
        # Flask's rule strings use converters only for UUID-free IDs in this module.
        request_path = rule.rule.replace("<event_id>", "event-1").replace("<category_id>", "category-1").replace("<expense_id>", "expense-1")
        method = next(method for method in rule.methods if method not in {"HEAD", "OPTIONS"})
        assert client.open(request_path, method=method).status_code == 401
