from types import SimpleNamespace

import jwt
from flask import Flask

from eventforge.errors import AuthenticationError
from eventforge.tasks.routes import task_bp


class TaskServiceStub:
    def list(self, event_id, user_id, query):
        assert event_id == "event-1"
        assert user_id == "user-1"
        return [], 0, 1, 20


def _client():
    app = Flask(__name__)
    app.extensions["settings"] = SimpleNamespace(jwt_secret="test-secret", jwt_algorithm="HS256")
    app.extensions["services"] = {"task_service": TaskServiceStub()}
    @app.errorhandler(AuthenticationError)
    def authentication_error(error):
        return {"message": error.message}, 401
    app.register_blueprint(task_bp, url_prefix="/events/<event_id>/tasks")
    return app.test_client()


def _headers():
    token = jwt.encode({"sub": "user-1"}, "test-secret", algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_task_blueprint_is_prefix_free_and_registered_once_per_event():
    client = _client()
    paths = {rule.rule for rule in client.application.url_map.iter_rules()}
    assert "/events/<event_id>/tasks" in paths
    assert "/tasks" not in paths
    assert "/events/<event_id>/tasks/events/<event_id>/tasks" not in paths


def test_task_list_requires_security_decorator_and_passes_event_and_owner():
    client = _client()
    assert client.get("/events/event-1/tasks").status_code == 401
    response = client.get("/events/event-1/tasks", headers=_headers())
    assert response.status_code == 200
    assert response.get_json() == {"items": [], "total": 0, "page": 1, "size": 20}
