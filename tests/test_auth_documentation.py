from __future__ import annotations

import jwt

from eventforge.app import create_app
from eventforge.config import Settings


def _client():
    app = create_app(Settings(
        database_url="postgresql://unused-for-route-unit-tests",
        jwt_secret="auth-documentation-test-secret",
        scheduler_enabled=False,
    ))
    app.config.update(TESTING=True)
    inserted = []
    app.extensions["database"].execute = lambda sql, params: inserted.append((sql, params))
    return app.test_client(), inserted


def _assert_auth_error(response):
    assert response.status_code == 401
    body = response.get_json()
    assert body["status"] == 401
    assert {"timestamp", "status", "error", "message", "path"} <= set(body)


def test_registration_returns_safe_identity_and_usable_bearer_token():
    client, inserted = _client()

    response = client.post("/auth/register", json={
        "email": "  New.User@example.test ", "password": "correct-horse-battery-staple",
    })

    assert response.status_code == 201
    body = response.get_json()
    assert set(body) == {"id", "email", "accessToken", "tokenType"}
    assert body["email"] == "new.user@example.test"
    assert body["tokenType"] == "Bearer"
    claims = jwt.decode(body["accessToken"], "auth-documentation-test-secret", algorithms=["HS256"])
    assert claims["sub"] == body["id"]
    assert len(inserted) == 1
    assert inserted[0][1][2] not in body.values()


def test_documentation_and_spec_require_bearer_auth_and_describe_it():
    client, _ = _client()

    for path in ("/docs", "/openapi.json"):
        _assert_auth_error(client.get(path))
        _assert_auth_error(client.get(path, headers={"Authorization": "Bearer invalid"}))

    token = jwt.encode({"sub": "documentation-user"}, "auth-documentation-test-secret", algorithm="HS256")
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/docs", headers=headers).status_code == 200
    specification = client.get("/openapi.json", headers=headers)
    assert specification.status_code == 200
    spec = specification.get_json()
    assert spec["paths"]["/docs"]["get"]["security"] == [{"bearerAuth": []}]
    assert spec["paths"]["/openapi.json"]["get"]["security"] == [{"bearerAuth": []}]
    assert spec["paths"]["/auth/register"]["post"]["security"] == []
    assert spec["paths"]["/auth/login"]["post"]["security"] == []
    registered = spec["components"]["schemas"]["RegisteredUser"]
    assert set(registered["required"]) == {"id", "email", "accessToken", "tokenType"}
    assert "password" not in registered["properties"]
