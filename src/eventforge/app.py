"""Oracle-backed Bottle application for EventForge."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from bottle import Bottle, HTTPResponse, request, response, run

from .database import database_from_environment, oracledb
from .security import JwtCodec, PasswordHasher

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EVENT_STATUSES = {"DRAFT", "PLANNED", "ACTIVE", "COMPLETED", "CANCELLED"}
TASK_STATUSES = {"TODO", "IN_PROGRESS", "BLOCKED", "COMPLETED"}
TASK_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "URGENT"}
RSVP_STATUSES = {"PENDING", "ACCEPTED", "DECLINED", "MAYBE"}
TASK_TRANSITIONS = {
    "TODO": {"IN_PROGRESS", "BLOCKED"},
    "IN_PROGRESS": {"BLOCKED", "COMPLETED"},
    "BLOCKED": {"IN_PROGRESS"},
    "COMPLETED": set(),
}
RSVP_TRANSITIONS = {
    "PENDING": {"ACCEPTED", "DECLINED", "MAYBE"},
    "MAYBE": {"ACCEPTED", "DECLINED"},
    "ACCEPTED": set(),
    "DECLINED": set(),
}


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def fail(status, code, message, details=None):
    raise ApiError(status, code, message, details)


def now():
    return datetime.now(timezone.utc).isoformat()


def parse_body():
    if not isinstance(request.json, dict):
        fail(400, "INVALID_JSON", "Request body must be a JSON object")
    return request.json


def required_text(data, field):
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        fail(422, "VALIDATION_ERROR", f"{field} is required")
    return value.strip()


def decimal_value(value, field, positive=False):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        fail(422, "VALIDATION_ERROR", f"{field} must be a decimal")
    if amount < 0 or (positive and amount <= 0):
        rule = "positive" if positive else "nonnegative"
        fail(422, "VALIDATION_ERROR", f"{field} must be {rule}")
    return amount.quantize(Decimal(".01"))


def date_value(value, field):
    if not isinstance(value, str):
        fail(422, "VALIDATION_ERROR", f"{field} must be ISO-8601")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail(422, "VALIDATION_ERROR", f"{field} must be ISO-8601")


def serialise(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if hasattr(value, "read"):
        return value.read()
    return value


def path_parameter(name, description="Resource identifier"):
    return {"name": name, "in": "path", "required": True,
            "description": description, "schema": {"type": "integer", "minimum": 1}}


def pagination_parameters(extra=()):
    result = [
        {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
        {"name": "page_size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
    ]
    result.extend(extra)
    return result


def openapi():
    """Return the complete public route contract, including operational routes."""
    json_body = lambda schema: {"required": True, "content": {"application/json": {"schema": schema}}}
    ok = {"200": {"description": "Successful response"}, "401": {"description": "Authentication required"}, "404": {"description": "Owned resource not found"}, "409": {"description": "Business-rule conflict"}, "422": {"description": "Validation error"}}
    created = dict(ok, **{"201": {"description": "Created"}})
    deleted = dict(ok, **{"204": {"description": "Deleted; no response body"}})
    event_id = path_parameter("event_id")
    resource_id = path_parameter("id")
    event_create_schema = {
        "type": "object",
        "required": ["name", "event_datetime", "venue"],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "event_datetime": {"type": "string", "format": "date-time"},
            "venue": {"type": "string", "minLength": 1, "description": "Nonblank event venue"},
            "status": {"type": "string", "enum": sorted(EVENT_STATUSES), "default": "DRAFT"},
            "capacity": {"type": "integer", "minimum": 1},
            "budget_limit": {"type": "number", "minimum": 0},
            "description": {"type": "string"},
        },
    }
    event_update_schema = {
        "type": "object",
        "description": "Supply one or more mutable event fields.",
        "properties": event_create_schema["properties"],
    }
    event_query_parameters = pagination_parameters((
        {"name": "status", "in": "query", "description": "Exact event status.", "schema": {"type": "string", "enum": sorted(EVENT_STATUSES)}},
        {"name": "q", "in": "query", "description": "Nonblank text searched across name, venue, and description.", "schema": {"type": "string", "minLength": 1, "maxLength": 200}},
        {"name": "date_from", "in": "query", "description": "Include events at or after this ISO-8601 date-time.", "schema": {"type": "string", "format": "date-time"}},
        {"name": "date_to", "in": "query", "description": "Include events at or before this ISO-8601 date-time.", "schema": {"type": "string", "format": "date-time"}},
        {"name": "sort", "in": "query", "description": "Whitelisted event sort field.", "schema": {"type": "string", "enum": ["id", "name", "event_datetime", "venue", "status", "created_at"], "default": "event_datetime"}},
        {"name": "order", "in": "query", "schema": {"type": "string", "enum": ["asc", "desc"], "default": "asc"}},
    ))
    paths = {
        "/health": {"get": {"summary": "Health check", "security": [], "responses": {"200": {"description": "Process is healthy"}}}},
        "/docs": {"get": {"summary": "Interactive API documentation", "security": [], "responses": {"200": {"description": "HTML documentation UI"}}}},
        "/openapi.json": {"get": {"summary": "OpenAPI document", "security": [], "responses": {"200": {"description": "OpenAPI 3.0 document"}}}},
        "/api/auth/register": {"post": {"summary": "Register", "security": [], "requestBody": json_body({"type": "object", "required": ["email", "password", "display_name"]}), "responses": created}},
        "/api/auth/login": {"post": {"summary": "Log in", "security": [], "requestBody": json_body({"type": "object", "required": ["email", "password"]}), "responses": ok}},
        "/api/events": {
            "get": {"summary": "List events", "parameters": event_query_parameters, "responses": ok},
            "post": {"summary": "Create event", "requestBody": json_body(event_create_schema), "responses": created},
        },
        "/api/events/{event_id}": {
            "get": {"summary": "Get event and financial totals", "parameters": [event_id], "responses": ok},
            "put": {"summary": "Update event", "parameters": [event_id], "requestBody": json_body(event_update_schema), "responses": ok},
            "delete": {"summary": "Delete event and all children", "parameters": [event_id], "responses": deleted},
        },
    }
    resources = {
        "tasks": {"fields": ["title", "status", "priority", "assignee", "deadline", "dependency_ids"], "extra": [{"name": "status", "in": "query", "schema": {"type": "string", "enum": sorted(TASK_STATUSES)}}, {"name": "priority", "in": "query", "schema": {"type": "string", "enum": sorted(TASK_PRIORITIES)}}, {"name": "assignee", "in": "query", "schema": {"type": "string"}}, {"name": "search", "in": "query", "schema": {"type": "string"}}, {"name": "sort", "in": "query", "schema": {"type": "string"}}, {"name": "order", "in": "query", "schema": {"type": "string", "enum": ["asc", "desc"]}}]},
        "invitations": {"fields": ["guest_name", "guest_email", "status"], "extra": [{"name": "status", "in": "query", "schema": {"type": "string", "enum": sorted(RSVP_STATUSES)}}, {"name": "search", "in": "query", "schema": {"type": "string"}}, {"name": "sort", "in": "query", "schema": {"type": "string"}}, {"name": "order", "in": "query", "schema": {"type": "string", "enum": ["asc", "desc"]}}]},
        "budget-categories": {"fields": ["name", "planned_amount"], "extra": []},
        "expenses": {"fields": ["category_id", "description", "amount", "expenditure_at"], "extra": []},
        "schedule": {"fields": ["title", "start_time", "end_time", "description"], "extra": [{"name": "search", "in": "query", "schema": {"type": "string"}}, {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["start_time", "-start_time", "title", "-title"]}}, {"name": "from", "in": "query", "schema": {"type": "string", "format": "date-time"}}, {"name": "to", "in": "query", "schema": {"type": "string", "format": "date-time"}}]},
        "vendors": {"fields": ["name", "service_type", "contact_details", "booking_status", "cost"], "extra": [{"name": "search", "in": "query", "schema": {"type": "string"}}, {"name": "service_type", "in": "query", "schema": {"type": "string"}}, {"name": "booking_status", "in": "query", "schema": {"type": "string"}}, {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["name", "-name", "cost", "-cost", "service_type", "-service_type"]}}]},
    }
    for name, definition in resources.items():
        schema = {"type": "object", "properties": {field: {"type": "string"} for field in definition["fields"]}}
        base = f"/api/events/{{event_id}}/{name}"
        paths[base] = {
            "get": {"summary": f"List {name}", "parameters": [event_id] + pagination_parameters(definition["extra"]), "responses": ok},
            "post": {"summary": f"Create {name[:-1]}", "parameters": [event_id], "requestBody": json_body(schema), "responses": created},
        }
        paths[f"{base}/{{id}}"] = {
            "get": {"summary": f"Get {name[:-1]}", "parameters": [event_id, resource_id], "responses": ok},
            "put": {"summary": f"Update {name[:-1]}", "parameters": [event_id, resource_id], "requestBody": json_body(schema), "responses": ok},
            "delete": {"summary": f"Delete {name[:-1]}", "parameters": [event_id, resource_id], "responses": deleted},
        }
    payment_schema = {"type": "object", "required": ["amount"], "properties": {"amount": {"type": "number"}, "payment_at": {"type": "string", "format": "date-time"}, "note": {"type": "string"}}}
    vendor_id = path_parameter("vendor_id")
    paths["/api/events/{event_id}/vendors/{vendor_id}/payments"] = {
        "get": {"summary": "List vendor payments", "parameters": [event_id, vendor_id] + pagination_parameters(({"name": "from", "in": "query", "schema": {"type": "string", "format": "date-time"}}, {"name": "to", "in": "query", "schema": {"type": "string", "format": "date-time"}}, {"name": "sort", "in": "query", "schema": {"type": "string", "enum": ["payment_at", "-payment_at", "amount", "-amount"]}})), "responses": ok},
        "post": {"summary": "Record vendor payment", "parameters": [event_id, vendor_id], "requestBody": json_body(payment_schema), "responses": created},
    }
    paths["/api/events/{event_id}/notifications"] = {"get": {"summary": "List notifications", "parameters": [event_id] + pagination_parameters(), "responses": ok}}
    paths["/api/events/{event_id}/notifications/{id}"] = {"patch": {"summary": "Set notification read state", "parameters": [event_id, resource_id], "requestBody": json_body({"type": "object", "required": ["read"], "properties": {"read": {"type": "boolean"}}}), "responses": ok}}
    paths["/api/events/{event_id}/activity"] = {"get": {"summary": "List event activity", "parameters": [event_id] + pagination_parameters(), "responses": ok}}
    for item in paths.values():
        for operation in item.values():
            operation.setdefault("security", [{"bearerAuth": []}])
    return {"openapi": "3.0.3", "info": {"title": "EventForge API", "version": "1.0.0"}, "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}}}


def create_app(db=None):
    db = db or database_from_environment()
    db.bootstrap()
    app = Bottle()
    codec = JwtCodec(os.getenv("JWT_SECRET", "development-only-change-me"), ttl_seconds=int(os.getenv("JWT_EXPIRY_SECONDS", "3600")))
    hasher = PasswordHasher()

    def rows(cursor):
        names = [item[0].lower() for item in cursor.description or []]
        return [{name: serialise(value) for name, value in zip(names, record)} for record in cursor.fetchall()]

    def one(cursor):
        result = rows(cursor)
        return result[0] if result else None

    def execute(cursor, sql, binds=None):
        cursor.execute(sql, binds or {})
        return cursor

    def insert(cursor, sql, binds):
        output = cursor.var(oracledb.NUMBER)
        cursor.execute(sql + " RETURNING id INTO :id", dict(binds, id=output))
        return int(output.getvalue()[0])

    def authenticate():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            fail(401, "AUTHENTICATION_REQUIRED", "Bearer token required")
        try:
            return int(codec.validate(header[7:]).subject)
        except Exception:
            fail(401, "INVALID_TOKEN", "Token is invalid or expired")

    def event(cursor, event_id, user_id, lock=False):
        suffix = " FOR UPDATE" if lock else ""
        value = one(execute(cursor, "SELECT * FROM eventforge_events WHERE id=:id AND owner_id=:owner" + suffix, {"id": event_id, "owner": user_id}))
        if not value:
            fail(404, "NOT_FOUND", "Event not found")
        return value

    def child(cursor, table, event_id, item_id):
        value = one(execute(cursor, f"SELECT * FROM {table} WHERE id=:id AND event_id=:event_id", {"id": item_id, "event_id": event_id}))
        if not value:
            fail(404, "NOT_FOUND", "Resource not found")
        return value

    def activity(cursor, event_id, user_id, action):
        insert(cursor, "INSERT INTO eventforge_activity (event_id,actor_user_id,action,details) VALUES (:event_id,:user_id,:action,:details)", {"event_id": event_id, "user_id": user_id, "action": action, "details": "{}"})

    def notification(cursor, event_id, kind, message):
        insert(cursor, "INSERT INTO eventforge_notifications (event_id,notification_type,message) VALUES (:event_id,:kind,:message)", {"event_id": event_id, "kind": kind, "message": message})

    def page(cursor, sql, binds):
        try:
            number = int(request.query.get("page", "1"))
            size = int(request.query.get("page_size", "20"))
        except (TypeError, ValueError):
            fail(422, "VALIDATION_ERROR", "page and page_size must be integers")
        if number < 1 or size < 1 or size > 100:
            fail(422, "VALIDATION_ERROR", "page must be at least 1 and page_size must be between 1 and 100")
        values = rows(execute(cursor, sql, binds))
        return {"items": values[(number - 1) * size:number * size], "total": len(values), "page": number, "page_size": size}

    def finance_collection_query(kind):
        """Validate finance collection filters and return SQL fragments safely.

        Sort expressions are selected only from this whitelist; every value supplied
        by a client is otherwise passed as a named Oracle bind.
        """
        definitions = {
            "category": {
                "allowed": {"page", "page_size", "search", "sort", "order", "from", "to", "min_planned_amount", "max_planned_amount"},
                "sort": {"id": "id", "name": "name", "planned_amount": "planned_amount", "created_at": "created_at"},
                "date_column": "created_at",
                "amount_column": "planned_amount",
                "amount_prefix": "planned_amount",
            },
            "expense": {
                "allowed": {"page", "page_size", "category_id", "search", "sort", "order", "from", "to", "min_amount", "max_amount"},
                "sort": {"id": "id", "description": "description", "amount": "amount", "expenditure_at": "expenditure_at", "created_at": "created_at"},
                "date_column": "expenditure_at",
                "amount_column": "amount",
                "amount_prefix": "amount",
            },
        }[kind]
        unknown = set(request.query.keys()) - definitions["allowed"]
        if unknown:
            fail(422, "VALIDATION_ERROR", "Unsupported query parameter", {"parameters": sorted(unknown)})
        where, binds = [], {}
        search = request.query.get("search")
        if search is not None:
            if not isinstance(search, str) or not search.strip() or len(search.strip()) > 200:
                fail(422, "VALIDATION_ERROR", "search must contain between 1 and 200 characters")
            where.append("LOWER(" + ("name" if kind == "category" else "description") + ") LIKE :search")
            binds["search"] = "%" + search.strip().lower() + "%"
        if kind == "expense" and request.query.get("category_id") is not None:
            raw_category = request.query.get("category_id")
            try:
                category_id = int(raw_category)
            except (TypeError, ValueError):
                fail(422, "VALIDATION_ERROR", "category_id must be a positive integer")
            if category_id < 1 or str(category_id) != raw_category:
                fail(422, "VALIDATION_ERROR", "category_id must be a positive integer")
            where.append("category_id=:filter_category_id")
            binds["filter_category_id"] = category_id
        start = date_value(request.query.get("from"), "from") if request.query.get("from") is not None else None
        end = date_value(request.query.get("to"), "to") if request.query.get("to") is not None else None
        if start and end and start > end:
            fail(422, "VALIDATION_ERROR", "from must not be after to")
        if start:
            where.append(definitions["date_column"] + ">=:from_time")
            binds["from_time"] = start
        if end:
            where.append(definitions["date_column"] + "<=:to_time")
            binds["to_time"] = end
        minimum = request.query.get("min_" + definitions["amount_prefix"])
        maximum = request.query.get("max_" + definitions["amount_prefix"])
        min_value = decimal_value(minimum, "min_" + definitions["amount_prefix"]) if minimum is not None else None
        max_value = decimal_value(maximum, "max_" + definitions["amount_prefix"]) if maximum is not None else None
        if min_value is not None and max_value is not None and min_value > max_value:
            fail(422, "VALIDATION_ERROR", "minimum amount must not exceed maximum amount")
        if min_value is not None:
            where.append(definitions["amount_column"] + ">=:min_amount")
            binds["min_amount"] = min_value
        if max_value is not None:
            where.append(definitions["amount_column"] + "<=:max_amount")
            binds["max_amount"] = max_value
        sort = request.query.get("sort", "id")
        if sort not in definitions["sort"]:
            fail(422, "VALIDATION_ERROR", "Invalid sort field")
        order = request.query.get("order", "asc").lower()
        if order not in {"asc", "desc"}:
            fail(422, "VALIDATION_ERROR", "order must be asc or desc")
        return where, binds, definitions["sort"][sort] + " " + order.upper() + ", id " + order.upper()

    def enforce_budget(cursor, event_id, user_id, proposed_total):
        """Lock the event and reject an expense write that would exceed its budget."""
        owner = event(cursor, event_id, user_id, lock=True)
        if proposed_total > Decimal(str(owner["budget_limit"])):
            fail(409, "BUDGET_LIMIT_EXCEEDED", "Expense would exceed the event budget limit")
        return owner

    def proposed_expense_total(cursor, event_id, old_amount, new_amount):
        actual = one(execute(cursor, "SELECT NVL(SUM(amount),0) actual FROM eventforge_expenses WHERE event_id=:event_id", {"event_id": event_id}))["actual"]
        return Decimal(str(actual)) - Decimal(str(old_amount)) + Decimal(str(new_amount))

    def category_totals(cursor, category):
        actual = one(execute(cursor, "SELECT NVL(SUM(amount),0) actual FROM eventforge_expenses WHERE category_id=:id", {"id": category["id"]}))["actual"]
        planned = Decimal(str(category["planned_amount"]))
        actual = Decimal(str(actual))
        return dict(category, planned=format(planned, ".2f"), actual=format(actual, ".2f"), remaining=format(planned - actual, ".2f"))

    def vendor_view(vendor):
        cost = Decimal(str(vendor["cost"]))
        paid = Decimal(str(vendor["paid_amount"]))
        return dict(vendor, outstanding_amount=format(cost - paid, ".2f"))

    def guarded(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except ApiError as error:
                body = {"error": {"code": error.code, "message": error.message, "details": error.details, "timestamp": now(), "correlation_id": request.environ.get("cid", "")}}
                return HTTPResponse(status=error.status, body=json.dumps(body), headers={"Content-Type": "application/json"})
            except Exception:
                return HTTPResponse(status=500, body=json.dumps({"error": {"code": "INTERNAL_ERROR", "message": "An internal error occurred", "timestamp": now(), "correlation_id": request.environ.get("cid", "")}}), headers={"Content-Type": "application/json"})
        return wrapper

    @app.hook("before_request")
    def request_id():
        request.environ["cid"] = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())

    @app.hook("after_request")
    def response_id():
        response.headers["X-Correlation-ID"] = request.environ["cid"]
        if response.content_type != "text/html":
            response.content_type = "application/json"

    @app.get("/health")
    def health():
        return {"status": "ok", "time": now()}

    @app.get("/openapi.json")
    def spec():
        return openapi()

    @app.get("/docs")
    def docs():
        response.content_type = "text/html"
        return '<!doctype html><div id="swagger-ui"></div><script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script><script>SwaggerUIBundle({url:"/openapi.json",dom_id:"#swagger-ui"})</script>'

    @app.post("/api/auth/register")
    @guarded
    def register():
        data = parse_body()
        email = required_text(data, "email").lower()
        password = required_text(data, "password")
        if not EMAIL.match(email) or len(password) < 8:
            fail(422, "VALIDATION_ERROR", "Invalid registration fields")
        try:
            with db.transaction() as connection:
                cursor = connection.cursor()
                user_id = insert(cursor, "INSERT INTO eventforge_users (email,password_hash,display_name) VALUES (:email,:password,:name)", {"email": email, "password": hasher.hash(password), "name": required_text(data, "display_name")})
                user = one(execute(cursor, "SELECT id,email,display_name,created_at FROM eventforge_users WHERE id=:id", {"id": user_id}))
        except Exception as exc:
            if getattr(getattr(exc, "args", [None])[0], "code", None) == 1:
                fail(409, "EMAIL_EXISTS", "Email is already registered")
            raise
        response.status = 201
        return {"user": user, "token": codec.issue(str(user_id))}

    @app.post("/api/auth/login")
    @guarded
    def login():
        data = parse_body()
        with db.transaction() as connection:
            cursor = connection.cursor()
            user = one(execute(cursor, "SELECT * FROM eventforge_users WHERE email=:email", {"email": required_text(data, "email").lower()}))
        if not user or not hasher.verify(required_text(data, "password"), user["password_hash"]):
            fail(401, "INVALID_CREDENTIALS", "Invalid email or password")
        return {"user": {key: user[key] for key in ("id", "email", "display_name", "created_at")}, "token": codec.issue(str(user["id"]))}

    @app.route("/api/events", method=["GET", "POST"])
    @guarded
    def events():
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor()
            if request.method == "GET":
                allowed = {"status", "q", "date_from", "date_to", "sort", "order", "page", "page_size"}
                unknown = set(request.query.keys()) - allowed
                if unknown:
                    fail(422, "VALIDATION_ERROR", "Unsupported query parameter", {"parameters": sorted(unknown)})

                binds = {"user_id": user_id}
                clauses = ["owner_id=:user_id"]
                status = request.query.get("status")
                if status is not None:
                    if status not in EVENT_STATUSES:
                        fail(422, "VALIDATION_ERROR", "Invalid event status")
                    clauses.append("status=:status")
                    binds["status"] = status

                query_text = request.query.get("q")
                if query_text is not None:
                    if not query_text.strip() or len(query_text.strip()) > 200:
                        fail(422, "VALIDATION_ERROR", "q must be nonblank and at most 200 characters")
                    binds["q"] = "%" + query_text.strip().lower() + "%"
                    clauses.append("(LOWER(name) LIKE :q OR LOWER(venue) LIKE :q OR LOWER(NVL(description,'')) LIKE :q)")

                date_from = request.query.get("date_from")
                date_to = request.query.get("date_to")
                from_value = date_value(date_from, "date_from") if date_from is not None else None
                to_value = date_value(date_to, "date_to") if date_to is not None else None
                # A zone-less ISO value is interpreted as UTC so mixed ISO inputs
                # remain comparable and are never allowed to trigger a server error.
                if from_value is not None and from_value.tzinfo is None:
                    from_value = from_value.replace(tzinfo=timezone.utc)
                if to_value is not None and to_value.tzinfo is None:
                    to_value = to_value.replace(tzinfo=timezone.utc)
                if from_value is not None and to_value is not None and from_value > to_value:
                    fail(422, "VALIDATION_ERROR", "date_from must not be after date_to")
                if from_value is not None:
                    clauses.append("event_datetime>=:date_from")
                    binds["date_from"] = from_value
                if to_value is not None:
                    clauses.append("event_datetime<=:date_to")
                    binds["date_to"] = to_value

                sortable = {
                    "id": "id", "name": "name", "event_datetime": "event_datetime",
                    "venue": "venue", "status": "status", "created_at": "created_at",
                }
                sort = request.query.get("sort", "event_datetime")
                order = request.query.get("order", "asc").lower()
                if sort not in sortable or order not in {"asc", "desc"}:
                    fail(422, "VALIDATION_ERROR", "Invalid event sort or order")
                sql = "SELECT * FROM eventforge_events WHERE " + " AND ".join(clauses)
                return page(cursor, sql + " ORDER BY " + sortable[sort] + " " + order.upper() + ", id", binds)
            data = parse_body()
            status = data.get("status", "DRAFT")
            if status not in EVENT_STATUSES:
                fail(422, "VALIDATION_ERROR", "Invalid event status")
            capacity = data.get("capacity")
            if capacity is not None and (type(capacity) is not int or capacity < 1):
                fail(422, "VALIDATION_ERROR", "capacity must be a positive integer")
            event_id = insert(cursor, "INSERT INTO eventforge_events (owner_id,name,event_datetime,venue,capacity,budget_limit,status,description) VALUES (:owner,:name,:time,:venue,:capacity,:budget,:status,:description)", {"owner": user_id, "name": required_text(data, "name"), "time": date_value(required_text(data, "event_datetime"), "event_datetime"), "venue": required_text(data, "venue"), "capacity": capacity, "budget": decimal_value(data.get("budget_limit", 0), "budget_limit"), "status": status, "description": data.get("description")})
            activity(cursor, event_id, user_id, "EVENT_CREATED")
            response.status = 201
            return event(cursor, event_id, user_id)

    @app.route("/api/events/<event_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def event_route(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor()
            old = event(cursor, event_id, user_id, request.method != "GET")
            if request.method == "GET":
                sums = one(execute(cursor, "SELECT NVL((SELECT SUM(planned_amount) FROM eventforge_categories WHERE event_id=:id),0) planned, NVL((SELECT SUM(amount) FROM eventforge_expenses WHERE event_id=:id),0) actual FROM dual", {"id": event_id}))
                return dict(old, aggregate={"planned": serialise(sums["planned"]), "actual": serialise(sums["actual"]), "remaining": format(Decimal(str(old["budget_limit"])) - Decimal(str(sums["actual"])), ".2f")})
            if request.method == "DELETE":
                for table in ("eventforge_task_dependencies",):
                    execute(cursor, f"DELETE FROM {table} WHERE task_id IN (SELECT id FROM eventforge_tasks WHERE event_id=:id) OR dependency_id IN (SELECT id FROM eventforge_tasks WHERE event_id=:id)", {"id": event_id})
                for table in ("eventforge_payments", "eventforge_expenses", "eventforge_tasks", "eventforge_invitations", "eventforge_categories", "eventforge_schedule", "eventforge_vendors", "eventforge_notifications", "eventforge_activity"):
                    execute(cursor, f"DELETE FROM {table} WHERE event_id=:id", {"id": event_id})
                execute(cursor, "DELETE FROM eventforge_events WHERE id=:id AND owner_id=:owner", {"id": event_id, "owner": user_id})
                response.status = 204
                return ""
            data = parse_body()
            values = {"id": event_id, "owner": user_id}
            changes = []
            for name in ("name", "venue", "description"):
                if name in data:
                    values[name] = required_text(data, name) if name == "name" else data[name]
                    changes.append(f"{name}=:{name}")
            if "status" in data:
                if data["status"] not in EVENT_STATUSES:
                    fail(422, "VALIDATION_ERROR", "Invalid event status")
                values["status"] = data["status"]
                changes.append("status=:status")
            if "capacity" in data:
                if type(data["capacity"]) is not int or data["capacity"] < old["confirmed_guest_count"]:
                    fail(422, "VALIDATION_ERROR", "capacity cannot be below confirmed guests")
                values["capacity"] = data["capacity"]
                changes.append("capacity=:capacity")
            if "event_datetime" in data:
                values["event_datetime"] = date_value(data["event_datetime"], "event_datetime")
                changes.append("event_datetime=:event_datetime")
            if "budget_limit" in data:
                values["budget_limit"] = decimal_value(data["budget_limit"], "budget_limit")
                changes.append("budget_limit=:budget_limit")
            if not changes:
                fail(422, "VALIDATION_ERROR", "No mutable fields supplied")
            execute(cursor, "UPDATE eventforge_events SET " + ",".join(changes) + " WHERE id=:id AND owner_id=:owner", values)
            activity(cursor, event_id, user_id, "EVENT_UPDATED")
            return event(cursor, event_id, user_id)

    def validate_collection_query(allowed):
        unknown = set(request.query.keys()) - set(allowed)
        if unknown:
            fail(422, "VALIDATION_ERROR", "Unsupported query parameter: " + sorted(unknown)[0])

    def collection_page(cursor, sql, binds, allowed_sorts, default_sort):
        """Strict, resource-local collection query parsing (never clamps bad input)."""
        try:
            number = int(request.query.get("page", "1"))
            size = int(request.query.get("page_size", "20"))
        except ValueError:
            fail(422, "VALIDATION_ERROR", "page and page_size must be integers")
        if number < 1 or not 1 <= size <= 100:
            fail(422, "VALIDATION_ERROR", "page must be positive and page_size must be between 1 and 100")
        sort = request.query.get("sort", default_sort)
        direction = request.query.get("order", "asc").lower()
        if sort not in allowed_sorts or direction not in {"asc", "desc"}:
            fail(422, "VALIDATION_ERROR", "Invalid sort or order")
        values = rows(execute(cursor, sql + " ORDER BY " + allowed_sorts[sort] + " " + direction.upper() + ", id", binds))
        start = (number - 1) * size
        return {"items": values[start:start + size], "total": len(values), "page": number, "page_size": size}

    def validate_dependencies(cursor, event_id, task_id, dependency_ids):
        if not isinstance(dependency_ids, list) or any(type(value) is not int for value in dependency_ids) or len(set(dependency_ids)) != len(dependency_ids):
            fail(422, "VALIDATION_ERROR", "dependency_ids must be a unique array of integers")
        if task_id in dependency_ids:
            fail(409, "TASK_DEPENDENCY_CONFLICT", "A task cannot depend on itself")
        for dependency_id in dependency_ids:
            if not one(execute(cursor, "SELECT id FROM eventforge_tasks WHERE id=:id AND event_id=:event_id", {"id": dependency_id, "event_id": event_id})):
                fail(409, "TASK_DEPENDENCY_CONFLICT", "Dependencies must belong to the event")
            todo, seen = [dependency_id], set()
            while todo:
                current = todo.pop()
                if current == task_id:
                    fail(409, "TASK_DEPENDENCY_CONFLICT", "Task dependency would create a cycle")
                if current not in seen:
                    seen.add(current)
                    todo.extend(row["dependency_id"] for row in rows(execute(cursor, "SELECT dependency_id FROM eventforge_task_dependencies WHERE task_id=:id", {"id": current})))

    def task_deadline_notifications(cursor, event_id, task):
        deadline = task.get("deadline")
        if deadline:
            notification(cursor, event_id, "deadline", "Task '%s' has a deadline" % task["title"])
            due = deadline if isinstance(deadline, datetime) else date_value(str(deadline), "deadline")
            if due < datetime.now(timezone.utc) and task["status"] != "COMPLETED":
                notification(cursor, event_id, "overdue-task", "Task '%s' is overdue" % task["title"])

    @app.route("/api/events/<event_id:int>/tasks", method=["GET", "POST"])
    @guarded
    def tasks(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id)
            if request.method == "GET":
                validate_collection_query({"page", "page_size", "status", "priority", "assignee", "search", "sort", "order"})
                binds, clauses = {"event_id": event_id}, ["event_id=:event_id"]
                status = request.query.get("status")
                priority = request.query.get("priority")
                assignee = request.query.get("assignee")
                search = request.query.get("search")
                if status is not None:
                    if status not in TASK_STATUSES: fail(422, "VALIDATION_ERROR", "Invalid task status")
                    clauses.append("status=:status"); binds["status"] = status
                if priority is not None:
                    if priority not in TASK_PRIORITIES: fail(422, "VALIDATION_ERROR", "Invalid task priority")
                    clauses.append("priority=:priority"); binds["priority"] = priority
                if assignee is not None:
                    clauses.append("assignee=:assignee"); binds["assignee"] = assignee
                if search is not None:
                    if not search.strip(): fail(422, "VALIDATION_ERROR", "search must not be blank")
                    clauses.append("(LOWER(title) LIKE :search OR LOWER(description) LIKE :search)"); binds["search"] = "%" + search.lower() + "%"
                return collection_page(cursor, "SELECT * FROM eventforge_tasks WHERE " + " AND ".join(clauses), binds, {"id": "id", "title": "title", "status": "status", "priority": "priority", "deadline": "deadline", "created_at": "created_at"}, "id")
            data = parse_body(); status = data.get("status", "TODO"); priority = data.get("priority")
            if status != "TODO": fail(422, "VALIDATION_ERROR", "New tasks must start in TODO")
            if priority not in TASK_PRIORITIES: fail(422, "VALIDATION_ERROR", "priority must be LOW, MEDIUM, HIGH, or URGENT")
            assignee = data.get("assignee")
            if assignee is not None and (not isinstance(assignee, str) or not assignee.strip()): fail(422, "VALIDATION_ERROR", "assignee must be a nonblank string or null")
            task_id = insert(cursor, "INSERT INTO eventforge_tasks (event_id,title,description,status,priority,assignee,deadline) VALUES (:event_id,:title,:description,:status,:priority,:assignee,:deadline)", {"event_id": event_id, "title": required_text(data, "title"), "description": data.get("description"), "status": status, "priority": priority, "assignee": assignee.strip() if assignee else None, "deadline": date_value(data["deadline"], "deadline") if data.get("deadline") else None})
            validate_dependencies(cursor, event_id, task_id, data.get("dependency_ids", []))
            for dependency_id in data.get("dependency_ids", []): execute(cursor, "INSERT INTO eventforge_task_dependencies (task_id,dependency_id) VALUES (:task,:dependency)", {"task": task_id, "dependency": dependency_id})
            value = child(cursor, "eventforge_tasks", event_id, task_id); activity(cursor, event_id, user_id, "TASK_CREATED"); task_deadline_notifications(cursor, event_id, value)
            response.status = 201; return value

    @app.route("/api/events/<event_id:int>/tasks/<task_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def task(event_id, task_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); old = child(cursor, "eventforge_tasks", event_id, task_id)
            if request.method == "GET": return old
            if request.method == "DELETE":
                if one(execute(cursor, "SELECT 1 FROM eventforge_task_dependencies WHERE dependency_id=:id FETCH FIRST 1 ROWS ONLY", {"id": task_id})): fail(409, "TASK_DEPENDENCY_CONFLICT", "Other tasks depend on this task")
                execute(cursor, "DELETE FROM eventforge_task_dependencies WHERE task_id=:id", {"id": task_id}); execute(cursor, "DELETE FROM eventforge_tasks WHERE id=:id", {"id": task_id}); activity(cursor, event_id, user_id, "TASK_DELETED"); response.status = 204; return ""
            data = parse_body(); status = data.get("status", old["status"])
            if status not in TASK_STATUSES: fail(422, "VALIDATION_ERROR", "Invalid task status")
            if old["status"] == "COMPLETED" and status != "COMPLETED": fail(409, "TASK_COMPLETED_IMMUTABLE", "Completed tasks cannot be reopened")
            if status != old["status"] and status not in TASK_TRANSITIONS[old["status"]]: fail(409, "INVALID_TASK_TRANSITION", "Invalid task lifecycle transition")
            if status == "COMPLETED" and one(execute(cursor, "SELECT 1 FROM eventforge_task_dependencies d JOIN eventforge_tasks t ON t.id=d.dependency_id WHERE d.task_id=:id AND t.status<>'COMPLETED' FETCH FIRST 1 ROWS ONLY", {"id": task_id})): fail(409, "INCOMPLETE_DEPENDENCIES", "All prerequisites must be completed")
            priority = data.get("priority", old["priority"])
            if priority not in TASK_PRIORITIES: fail(422, "VALIDATION_ERROR", "Invalid task priority")
            assignee = data.get("assignee", old["assignee"])
            if assignee is not None and (not isinstance(assignee, str) or not assignee.strip()): fail(422, "VALIDATION_ERROR", "assignee must be a nonblank string or null")
            if "dependency_ids" in data:
                validate_dependencies(cursor, event_id, task_id, data["dependency_ids"]); execute(cursor, "DELETE FROM eventforge_task_dependencies WHERE task_id=:id", {"id": task_id})
                for dependency_id in data["dependency_ids"]: execute(cursor, "INSERT INTO eventforge_task_dependencies (task_id,dependency_id) VALUES (:task,:dependency)", {"task": task_id, "dependency": dependency_id})
            execute(cursor, "UPDATE eventforge_tasks SET title=:title,description=:description,status=:status,priority=:priority,assignee=:assignee,deadline=:deadline WHERE id=:id", {"title": required_text(data, "title") if "title" in data else old["title"], "description": data.get("description", old["description"]), "status": status, "priority": priority, "assignee": assignee.strip() if assignee else None, "deadline": date_value(data["deadline"], "deadline") if "deadline" in data and data["deadline"] else (None if data.get("deadline") is None and "deadline" in data else old["deadline"]), "id": task_id})
            value = child(cursor, "eventforge_tasks", event_id, task_id); activity(cursor, event_id, user_id, "TASK_UPDATED"); task_deadline_notifications(cursor, event_id, value)
            return value

    @app.route("/api/events/<event_id:int>/invitations", method=["GET", "POST"])
    @guarded
    def invitations(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id)
            if request.method == "GET":
                validate_collection_query({"page", "page_size", "status", "search", "sort", "order"})
                binds, clauses = {"event_id": event_id}, ["event_id=:event_id"]
                status, search = request.query.get("status"), request.query.get("search")
                if status is not None:
                    if status not in RSVP_STATUSES: fail(422, "VALIDATION_ERROR", "Invalid RSVP status")
                    clauses.append("status=:status"); binds["status"] = status
                if search is not None:
                    if not search.strip(): fail(422, "VALIDATION_ERROR", "search must not be blank")
                    clauses.append("(LOWER(guest_name) LIKE :search OR LOWER(guest_email) LIKE :search)"); binds["search"] = "%" + search.lower() + "%"
                return collection_page(cursor, "SELECT * FROM eventforge_invitations WHERE " + " AND ".join(clauses), binds, {"id": "id", "guest_name": "guest_name", "guest_email": "guest_email", "status": "status", "created_at": "created_at"}, "id")
            data = parse_body(); status = data.get("status", "PENDING")
            if status not in RSVP_STATUSES: fail(422, "VALIDATION_ERROR", "Invalid RSVP status")
            if not EMAIL.match(required_text(data, "guest_email").lower()): fail(422, "VALIDATION_ERROR", "guest_email must be valid")
            locked_event = event(cursor, event_id, user_id, lock=True)
            if status == "ACCEPTED" and locked_event["capacity"] is not None and locked_event["confirmed_guest_count"] >= locked_event["capacity"]: fail(409, "EVENT_CAPACITY_REACHED", "Event capacity has been reached")
            invitation_id = insert(cursor, "INSERT INTO eventforge_invitations (event_id,guest_name,guest_email,status) VALUES (:event_id,:name,:email,:status)", {"event_id": event_id, "name": required_text(data, "guest_name"), "email": required_text(data, "guest_email").lower(), "status": status})
            if status == "ACCEPTED": execute(cursor, "UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count+1 WHERE id=:id", {"id": event_id})
            activity(cursor, event_id, user_id, "INVITATION_CREATED"); notification(cursor, event_id, "invitation", "Invitation RSVP recorded for " + required_text(data, "guest_name"))
            response.status = 201; return child(cursor, "eventforge_invitations", event_id, invitation_id)

    @app.route("/api/events/<event_id:int>/invitations/<invitation_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def invitation(event_id, invitation_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); old = child(cursor, "eventforge_invitations", event_id, invitation_id)
            if request.method == "GET": event(cursor, event_id, user_id); return old
            locked_event = event(cursor, event_id, user_id, lock=True)
            if request.method == "DELETE":
                if old["status"] == "ACCEPTED": execute(cursor, "UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count-1 WHERE id=:id AND confirmed_guest_count>0", {"id": event_id})
                execute(cursor, "DELETE FROM eventforge_invitations WHERE id=:id AND event_id=:event_id", {"id": invitation_id, "event_id": event_id}); activity(cursor, event_id, user_id, "INVITATION_DELETED"); notification(cursor, event_id, "invitation", "Invitation deleted for " + old["guest_name"]); response.status = 204; return ""
            data = parse_body(); status = data.get("status", old["status"])
            if status not in RSVP_STATUSES: fail(422, "VALIDATION_ERROR", "Invalid RSVP status")
            if status != old["status"] and status not in RSVP_TRANSITIONS[old["status"]]: fail(409, "INVALID_RSVP_TRANSITION", "Invalid RSVP status transition")
            if status == "ACCEPTED" and old["status"] != "ACCEPTED" and locked_event["capacity"] is not None and locked_event["confirmed_guest_count"] >= locked_event["capacity"]: fail(409, "EVENT_CAPACITY_REACHED", "Event capacity has been reached")
            email = data.get("guest_email", old["guest_email"])
            if not isinstance(email, str) or not EMAIL.match(email.lower()): fail(422, "VALIDATION_ERROR", "guest_email must be valid")
            if old["status"] != "ACCEPTED" and status == "ACCEPTED": execute(cursor, "UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count+1 WHERE id=:id", {"id": event_id})
            if old["status"] == "ACCEPTED" and status != "ACCEPTED": execute(cursor, "UPDATE eventforge_events SET confirmed_guest_count=confirmed_guest_count-1 WHERE id=:id AND confirmed_guest_count>0", {"id": event_id})
            execute(cursor, "UPDATE eventforge_invitations SET guest_name=:name,guest_email=:email,status=:status WHERE id=:id", {"name": required_text(data, "guest_name") if "guest_name" in data else old["guest_name"], "email": email.lower(), "status": status, "id": invitation_id})
            activity(cursor, event_id, user_id, "INVITATION_UPDATED"); notification(cursor, event_id, "invitation", "Invitation RSVP updated for " + (data.get("guest_name") or old["guest_name"]))
            return child(cursor, "eventforge_invitations", event_id, invitation_id)

    # Finance mutations include their audit row in the same database transaction.
    @app.route("/api/events/<event_id:int>/budget-categories", method=["GET", "POST"])
    @guarded
    def categories(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id)
            if request.method == "GET":
                clauses, binds, order = finance_collection_query("category")
                binds["event_id"] = event_id
                sql = "SELECT * FROM eventforge_categories WHERE event_id=:event_id"
                if clauses:
                    sql += " AND " + " AND ".join(clauses)
                result = page(cursor, sql + " ORDER BY " + order, binds)
                result["items"] = [category_totals(cursor, item) for item in result["items"]]
                return result
            data = parse_body()
            category_id = insert(cursor, "INSERT INTO eventforge_categories (event_id,name,planned_amount) VALUES (:event_id,:name,:planned)", {"event_id": event_id, "name": required_text(data, "name"), "planned": decimal_value(data.get("planned_amount", 0), "planned_amount")})
            activity(cursor, event_id, user_id, "CATEGORY_CREATED")
            response.status = 201
            return category_totals(cursor, child(cursor, "eventforge_categories", event_id, category_id))

    @app.route("/api/events/<event_id:int>/budget-categories/<category_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def category(event_id, category_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); old = child(cursor, "eventforge_categories", event_id, category_id)
            if request.method == "GET": return category_totals(cursor, old)
            if request.method == "DELETE":
                if one(execute(cursor, "SELECT 1 FROM eventforge_expenses WHERE category_id=:id FETCH FIRST 1 ROWS ONLY", {"id": category_id})):
                    fail(409, "CATEGORY_HAS_EXPENSES", "Category has expenses")
                execute(cursor, "DELETE FROM eventforge_categories WHERE id=:id", {"id": category_id})
                activity(cursor, event_id, user_id, "CATEGORY_DELETED")
                response.status = 204
                return ""
            data = parse_body(); planned = decimal_value(data.get("planned_amount", old["planned_amount"]), "planned_amount")
            actual = Decimal(category_totals(cursor, old)["actual"])
            if planned < actual: fail(409, "CATEGORY_LIMIT_BELOW_SPEND", "planned_amount cannot be below actual spending")
            name = required_text(data, "name") if "name" in data else old["name"]
            execute(cursor, "UPDATE eventforge_categories SET name=:name,planned_amount=:planned WHERE id=:id", {"name": name, "planned": planned, "id": category_id})
            activity(cursor, event_id, user_id, "CATEGORY_UPDATED")
            return category_totals(cursor, child(cursor, "eventforge_categories", event_id, category_id))

    @app.route("/api/events/<event_id:int>/expenses", method=["GET", "POST"])
    @guarded
    def expenses(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id, lock=request.method == "POST")
            if request.method == "GET":
                clauses, binds, order = finance_collection_query("expense")
                binds["event_id"] = event_id
                sql = "SELECT * FROM eventforge_expenses WHERE event_id=:event_id"
                if clauses:
                    sql += " AND " + " AND ".join(clauses)
                return page(cursor, sql + " ORDER BY " + order, binds)
            data = parse_body(); category_id = data.get("category_id")
            if type(category_id) is not int or category_id < 1: fail(422, "VALIDATION_ERROR", "category_id is required")
            amount = decimal_value(data.get("amount"), "amount", True)
            # The event row is locked before calculating and writing the new total.
            enforce_budget(cursor, event_id, user_id, proposed_expense_total(cursor, event_id, 0, amount))
            child(cursor, "eventforge_categories", event_id, category_id)
            expense_id = insert(cursor, "INSERT INTO eventforge_expenses (event_id,category_id,description,amount,expenditure_at) VALUES (:event_id,:category,:description,:amount,:at)", {"event_id": event_id, "category": category_id, "description": required_text(data, "description"), "amount": amount, "at": date_value(data["expenditure_at"], "expenditure_at") if data.get("expenditure_at") else datetime.now(timezone.utc)})
            activity(cursor, event_id, user_id, "EXPENSE_CREATED")
            response.status = 201
            return child(cursor, "eventforge_expenses", event_id, expense_id)

    @app.route("/api/events/<event_id:int>/expenses/<expense_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def expense(event_id, expense_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id, lock=request.method == "PUT"); old = child(cursor, "eventforge_expenses", event_id, expense_id)
            if request.method == "GET": return old
            if request.method == "DELETE":
                execute(cursor, "DELETE FROM eventforge_expenses WHERE id=:id", {"id": expense_id})
                activity(cursor, event_id, user_id, "EXPENSE_DELETED")
                response.status = 204
                return ""
            data = parse_body(); category_id = data.get("category_id", old["category_id"])
            if type(category_id) is not int or category_id < 1: fail(422, "VALIDATION_ERROR", "category_id must be a positive integer")
            amount = decimal_value(data.get("amount", old["amount"]), "amount", True)
            # This locks before the total is calculated, so concurrent writes serialize.
            enforce_budget(cursor, event_id, user_id, proposed_expense_total(cursor, event_id, old["amount"], amount))
            child(cursor, "eventforge_categories", event_id, category_id)
            description = required_text(data, "description") if "description" in data else old["description"]
            expenditure_at = date_value(data["expenditure_at"], "expenditure_at") if "expenditure_at" in data else old["expenditure_at"]
            execute(cursor, "UPDATE eventforge_expenses SET category_id=:category,description=:description,amount=:amount,expenditure_at=:at WHERE id=:id", {"category": category_id, "description": description, "amount": amount, "at": expenditure_at, "id": expense_id})
            activity(cursor, event_id, user_id, "EXPENSE_UPDATED")
            return child(cursor, "eventforge_expenses", event_id, expense_id)

    # The remaining resource routes are intentionally available through a small shared CRUD implementation.
    def simple_resource(name, table, fields, amount=None):
        @app.route(f"/api/events/<event_id:int>/{name}", method=["GET", "POST"])
        @guarded
        def collection(event_id):
            user_id = authenticate()
            with db.transaction() as connection:
                cursor = connection.cursor(); event(cursor, event_id, user_id)
                if request.method == "GET":
                    result = page(cursor, f"SELECT * FROM {table} WHERE event_id=:event_id ORDER BY id", {"event_id": event_id})
                    if table == "eventforge_vendors":
                        result["items"] = [vendor_view(item) for item in result["items"]]
                    return result
                data = parse_body()
                values = {field: required_text(data, field) for field in fields}
                values["event_id"] = event_id
                if amount:
                    values[amount] = decimal_value(data.get(amount, 0), amount)
                columns = fields + ((amount,) if amount else ())
                item_id = insert(cursor, f"INSERT INTO {table} (event_id,{','.join(columns)}) VALUES (:event_id,{','.join(':' + field for field in columns)})", values)
                response.status = 201
                value = child(cursor, table, event_id, item_id)
                return vendor_view(value) if table == "eventforge_vendors" else value
        @app.route(f"/api/events/<event_id:int>/{name}/<item_id:int>", method=["GET", "PUT", "DELETE"])
        @guarded
        def item(event_id, item_id):
            user_id = authenticate()
            with db.transaction() as connection:
                cursor = connection.cursor(); event(cursor, event_id, user_id); old = child(cursor, table, event_id, item_id)
                if request.method == "GET": return vendor_view(old) if table == "eventforge_vendors" else old
                if request.method == "DELETE":
                    if table == "eventforge_vendors" and one(execute(cursor, "SELECT 1 FROM eventforge_payments WHERE vendor_id=:id FETCH FIRST 1 ROWS ONLY", {"id": item_id})): fail(409, "VENDOR_HAS_PAYMENTS", "Vendor has payments")
                    execute(cursor, f"DELETE FROM {table} WHERE id=:id", {"id": item_id}); response.status = 204; return ""
                data = parse_body(); sets = []; binds = {"id": item_id}
                for field in fields:
                    if field in data: sets.append(f"{field}=:{field}"); binds[field] = required_text(data, field)
                if amount and amount in data: sets.append(f"{amount}=:{amount}"); binds[amount] = decimal_value(data[amount], amount)
                if not sets: fail(422, "VALIDATION_ERROR", "No mutable fields supplied")
                execute(cursor, f"UPDATE {table} SET {','.join(sets)} WHERE id=:id", binds); value = child(cursor, table, event_id, item_id); return vendor_view(value) if table == "eventforge_vendors" else value
        return collection, item

    # The public vendor projection deliberately hides retired contact_name,
    # contact_email, and booking_reference persistence columns.
    def vendor_public(value):
        return {key: value[key] for key in ("id", "event_id", "name", "service_type", "contact_details", "booking_status", "cost", "paid_amount", "created_at") if key in value} | {"outstanding_amount": format(Decimal(str(value["cost"])) - Decimal(str(value["paid_amount"])), ".2f")}

    @app.route("/api/events/<event_id:int>/vendors", method=["GET", "POST"])
    @guarded
    def vendors(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id)
            if request.method == "GET":
                binds = {"event_id": event_id}
                sql = "SELECT * FROM eventforge_vendors WHERE event_id=:event_id"
                for field in ("service_type", "booking_status"):
                    if request.query.get(field):
                        binds[field] = required_text({field: request.query.get(field)}, field)
                        sql += f" AND {field}=:{field}"
                if request.query.get("search"):
                    binds["search"] = "%" + required_text({"search": request.query.search}, "search").lower() + "%"
                    sql += " AND (LOWER(name) LIKE :search OR LOWER(service_type) LIKE :search)"
                order = request.query.get("sort", "name")
                order_by = {"name": "name ASC", "-name": "name DESC", "cost": "cost ASC", "-cost": "cost DESC", "service_type": "service_type ASC", "-service_type": "service_type DESC"}
                if order not in order_by: fail(422, "VALIDATION_ERROR", "Invalid vendor sort")
                result = page(cursor, sql + " ORDER BY " + order_by[order] + ", id", binds)
                result["items"] = [vendor_public(item) for item in result["items"]]
                return result
            data = parse_body()
            values = {"event_id": event_id, "name": required_text(data, "name"), "service_type": required_text(data, "service_type"), "contact_details": data.get("contact_details"), "booking_status": required_text(data, "booking_status"), "cost": decimal_value(data.get("cost"), "cost")}
            if values["contact_details"] is not None and not isinstance(values["contact_details"], str): fail(422, "VALIDATION_ERROR", "contact_details must be a string or null")
            vendor_id = insert(cursor, "INSERT INTO eventforge_vendors (event_id,name,service_type,contact_details,booking_status,cost) VALUES (:event_id,:name,:service_type,:contact_details,:booking_status,:cost)", values)
            activity(cursor, event_id, user_id, "VENDOR_CREATED")
            response.status = 201; return vendor_public(child(cursor, "eventforge_vendors", event_id, vendor_id))

    @app.route("/api/events/<event_id:int>/vendors/<vendor_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def vendor(event_id, vendor_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); old = child(cursor, "eventforge_vendors", event_id, vendor_id)
            if request.method == "GET": return vendor_public(old)
            if request.method == "DELETE":
                if one(execute(cursor, "SELECT 1 FROM eventforge_payments WHERE vendor_id=:id FETCH FIRST 1 ROWS ONLY", {"id": vendor_id})): fail(409, "VENDOR_HAS_PAYMENTS", "Vendor has payments")
                execute(cursor, "DELETE FROM eventforge_vendors WHERE id=:id", {"id": vendor_id}); activity(cursor, event_id, user_id, "VENDOR_DELETED"); response.status = 204; return ""
            data = parse_body(); allowed = ("name", "service_type", "contact_details", "booking_status")
            sets, binds = [], {"id": vendor_id}
            for field in allowed:
                if field in data:
                    if field == "contact_details":
                        if data[field] is not None and not isinstance(data[field], str): fail(422, "VALIDATION_ERROR", "contact_details must be a string or null")
                        binds[field] = data[field]
                    else: binds[field] = required_text(data, field)
                    sets.append(f"{field}=:{field}")
            if "cost" in data: binds["cost"] = decimal_value(data["cost"], "cost"); sets.append("cost=:cost")
            if not sets: fail(422, "VALIDATION_ERROR", "No mutable fields supplied")
            execute(cursor, "UPDATE eventforge_vendors SET " + ",".join(sets) + " WHERE id=:id", binds)
            activity(cursor, event_id, user_id, "VENDOR_UPDATED")
            return vendor_public(child(cursor, "eventforge_vendors", event_id, vendor_id))

    @app.route("/api/events/<event_id:int>/schedule", method=["GET", "POST"])
    @guarded
    def schedule(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor()
            event(cursor, event_id, user_id)
            if request.method == "GET":
                start = date_value(request.query["from"], "from") if request.query.get("from") else None
                end = date_value(request.query["to"], "to") if request.query.get("to") else None
                if start and end and start > end:
                    fail(422, "VALIDATION_ERROR", "from must not be after to")
                sql = "SELECT * FROM eventforge_schedule WHERE event_id=:event_id"
                binds = {"event_id": event_id}
                if start:
                    sql += " AND end_time>=:from_time"
                    binds["from_time"] = start
                if end:
                    sql += " AND start_time<=:to_time"
                    binds["to_time"] = end
                if request.query.get("search"):
                    binds["search"] = "%" + required_text({"search": request.query.search}, "search").lower() + "%"
                    sql += " AND (LOWER(title) LIKE :search OR LOWER(description) LIKE :search)"
                order = request.query.get("sort", "start_time")
                order_by = {"start_time": "start_time ASC", "-start_time": "start_time DESC", "title": "title ASC", "-title": "title DESC"}
                if order not in order_by: fail(422, "VALIDATION_ERROR", "Invalid schedule sort")
                return page(cursor, sql + " ORDER BY " + order_by[order] + ", id", binds)
            data = parse_body()
            start = date_value(required_text(data, "start_time"), "start_time")
            end = date_value(required_text(data, "end_time"), "end_time")
            if start >= end:
                fail(422, "VALIDATION_ERROR", "start_time must precede end_time")
            overlap = one(execute(cursor, "SELECT id FROM eventforge_schedule WHERE event_id=:event_id AND start_time < :end_time AND end_time > :start_time FETCH FIRST 1 ROWS ONLY", {"event_id": event_id, "start_time": start, "end_time": end}))
            if overlap:
                fail(409, "SCHEDULE_OVERLAP", "Schedule intervals overlap")
            if "details" in data: fail(422, "VALIDATION_ERROR", "description replaces details")
            description = data.get("description")
            if description is not None and not isinstance(description, str): fail(422, "VALIDATION_ERROR", "description must be a string or null")
            item_id = insert(cursor, "INSERT INTO eventforge_schedule (event_id,title,start_time,end_time,description) VALUES (:event_id,:title,:start,:end,:description)", {"event_id": event_id, "title": required_text(data, "title"), "start": start, "end": end, "description": description})
            activity(cursor, event_id, user_id, "SCHEDULE_CREATED")
            response.status = 201
            return child(cursor, "eventforge_schedule", event_id, item_id)

    @app.route("/api/events/<event_id:int>/schedule/<item_id:int>", method=["GET", "PUT", "DELETE"])
    @guarded
    def schedule_item(event_id, item_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor()
            event(cursor, event_id, user_id)
            old = child(cursor, "eventforge_schedule", event_id, item_id)
            if request.method == "GET":
                return old
            if request.method == "DELETE":
                execute(cursor, "DELETE FROM eventforge_schedule WHERE id=:id", {"id": item_id})
                activity(cursor, event_id, user_id, "SCHEDULE_DELETED")
                response.status = 204
                return ""
            data = parse_body()
            if "details" in data: fail(422, "VALIDATION_ERROR", "description replaces details")
            start = date_value(data.get("start_time", old["start_time"]), "start_time")
            end = date_value(data.get("end_time", old["end_time"]), "end_time")
            if start >= end:
                fail(422, "VALIDATION_ERROR", "start_time must precede end_time")
            overlap = one(execute(cursor, "SELECT id FROM eventforge_schedule WHERE event_id=:event_id AND id<>:id AND start_time < :end_time AND end_time > :start_time FETCH FIRST 1 ROWS ONLY", {"event_id": event_id, "id": item_id, "start_time": start, "end_time": end}))
            if overlap:
                fail(409, "SCHEDULE_OVERLAP", "Schedule intervals overlap")
            description = data.get("description", old["description"])
            if description is not None and not isinstance(description, str): fail(422, "VALIDATION_ERROR", "description must be a string or null")
            execute(cursor, "UPDATE eventforge_schedule SET title=:title,start_time=:start,end_time=:end,description=:description WHERE id=:id", {"title": data.get("title", old["title"]), "start": start, "end": end, "description": description, "id": item_id})
            activity(cursor, event_id, user_id, "SCHEDULE_UPDATED")
            return child(cursor, "eventforge_schedule", event_id, item_id)

    @app.route("/api/events/<event_id:int>/vendors/<vendor_id:int>/payments", method=["GET", "POST"])
    @guarded
    def payments(event_id, vendor_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); vendor = child(cursor, "eventforge_vendors", event_id, vendor_id)
            if request.method == "GET":
                start = date_value(request.query["from"], "from") if request.query.get("from") else None
                end = date_value(request.query["to"], "to") if request.query.get("to") else None
                if start and end and start > end: fail(422, "VALIDATION_ERROR", "from must not be after to")
                binds = {"event_id": event_id, "vendor_id": vendor_id}
                sql = "SELECT * FROM eventforge_payments WHERE event_id=:event_id AND vendor_id=:vendor_id"
                if start: sql += " AND payment_at>=:from_time"; binds["from_time"] = start
                if end: sql += " AND payment_at<=:to_time"; binds["to_time"] = end
                order = request.query.get("sort", "payment_at")
                order_by = {"payment_at": "payment_at ASC", "-payment_at": "payment_at DESC", "amount": "amount ASC", "-amount": "amount DESC"}
                if order not in order_by: fail(422, "VALIDATION_ERROR", "Invalid payment sort")
                return page(cursor, sql + " ORDER BY " + order_by[order] + ", id", binds)
            data = parse_body(); amount = decimal_value(data.get("amount"), "amount", True)
            if Decimal(str(vendor["paid_amount"])) + amount > Decimal(str(vendor["cost"])): fail(409, "PAYMENT_EXCEEDS_COST", "Payment exceeds vendor cost")
            payment_id = insert(cursor, "INSERT INTO eventforge_payments (event_id,vendor_id,amount,payment_at,note) VALUES (:event_id,:vendor,:amount,:at,:note)", {"event_id": event_id, "vendor": vendor_id, "amount": amount, "at": date_value(data["payment_at"], "payment_at") if data.get("payment_at") else datetime.now(timezone.utc), "note": data.get("note")}); execute(cursor, "UPDATE eventforge_vendors SET paid_amount=paid_amount+:amount WHERE id=:id", {"amount": amount, "id": vendor_id}); activity(cursor, event_id, user_id, "VENDOR_PAYMENT_CREATED"); response.status = 201; return child(cursor, "eventforge_payments", event_id, payment_id)

    @app.get("/api/events/<event_id:int>/notifications")
    @guarded
    def notifications(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id)
            binds = {"event_id": event_id}; sql = "SELECT * FROM eventforge_notifications WHERE event_id=:event_id"
            if request.query.get("read") is not None:
                if request.query.read not in ("true", "false"): fail(422, "VALIDATION_ERROR", "read must be true or false")
                sql += " AND read_at " + ("IS NOT NULL" if request.query.read == "true" else "IS NULL")
            return page(cursor, sql + " ORDER BY id DESC", binds)

    @app.patch("/api/events/<event_id:int>/notifications/<notification_id:int>")
    @guarded
    def update_notification(event_id, notification_id):
        user_id = authenticate(); data = parse_body()
        if "read" not in data: fail(422, "VALIDATION_ERROR", "read is required")
        read = data["read"]
        if type(read) is not bool: fail(422, "VALIDATION_ERROR", "read must be boolean")
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); child(cursor, "eventforge_notifications", event_id, notification_id)
            execute(cursor, "UPDATE eventforge_notifications SET read_at=:read_at WHERE id=:id", {"read_at": datetime.now(timezone.utc) if read else None, "id": notification_id})
            activity(cursor, event_id, user_id, "NOTIFICATION_READ_STATE_UPDATED")
            return child(cursor, "eventforge_notifications", event_id, notification_id)

    @app.get("/api/events/<event_id:int>/activity")
    @guarded
    def activities(event_id):
        user_id = authenticate()
        with db.transaction() as connection:
            cursor = connection.cursor(); event(cursor, event_id, user_id); return page(cursor, "SELECT * FROM eventforge_activity WHERE event_id=:event_id ORDER BY id DESC", {"event_id": event_id})

    return app


app = create_app()

if __name__ == "__main__":
    run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), quiet=True)
