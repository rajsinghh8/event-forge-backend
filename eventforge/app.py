from __future__ import annotations

import atexit
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid4

from flask import Flask, g, jsonify, request

from .config import Settings
from .database import Database
from .errors import AuthorizationError, ConflictError, DomainError, NotFoundError, ValidationError
from .security import hash_password, require_auth, token_for, verify_password


def _value(value):
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def create_app(settings: Settings | None = None) -> Flask:
    """Create the EventForge HTTP application and register all resource modules."""
    app = Flask(__name__)
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    app.extensions["settings"] = settings
    app.extensions["services"] = {"database": database}
    # These aliases keep injected resource modules and external integrations compatible.
    app.extensions["database"] = database
    app.extensions["db"] = database
    logging.basicConfig(level=logging.INFO)

    @app.errorhandler(DomainError)
    def domain_error(error):
        return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=error.status_code,
                       error=error.__class__.__name__, message=error.message, path=request.path), error.status_code

    @app.errorhandler(404)
    def not_found(error):
        return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=404, error="NotFound",
                       message="Resource not found", path=request.path), 404

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Unhandled request failure")
        return jsonify(timestamp=datetime.now(timezone.utc).isoformat(), status=500, error="InternalServerError",
                       message="An internal error occurred", path=request.path), 500

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/register")
    def register():
        body = request.get_json(silent=True)
        if (not isinstance(body, dict) or not isinstance(body.get("email"), str)
                or not isinstance(body.get("password"), str) or len(body["password"]) < 8):
            raise ValidationError("email and password (minimum 8 characters) are required")
        email = body["email"].strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValidationError("email is invalid")
        user_id = uuid4()
        try:
            database.execute("INSERT INTO users (id,email,password_hash) VALUES (%s,%s,%s)",
                             (user_id, email, hash_password(body["password"])))
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ConflictError("Email is already registered") from exc
            raise
        return jsonify({"id": str(user_id), "email": email}), 201

    @app.post("/auth/login")
    def login():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("Request body must be a JSON object")
        row = database.fetchone("SELECT id,password_hash FROM users WHERE email=%s",
                                (str(body.get("email", "")).strip().lower(),))
        if row is None or not verify_password(str(body.get("password", "")), row["password_hash"]):
            from .errors import AuthenticationError
            raise AuthenticationError("Invalid credentials")
        return {"accessToken": token_for(row["id"]), "tokenType": "Bearer"}

    def event_for_owner(event_id, connection=None, lock=False):
        sql = "SELECT * FROM events WHERE id=%s" + (" FOR UPDATE" if lock else "")
        if connection is None:
            row = database.fetchone(sql, (event_id,))
        else:
            with connection.cursor() as cursor:
                cursor.execute(sql, (event_id,))
                row = cursor.fetchone()
        if row is None:
            raise NotFoundError("Event not found")
        if str(row["owner_id"]) != str(g.user_id):
            raise AuthorizationError("You do not own this event")
        return row

    def event_output(row, accepted_count=None, actual=None):
        result = {"id": str(row["id"]), "ownerId": str(row["owner_id"]), "name": row["name"],
                  "description": row["description"], "startAt": _value(row["start_at"]),
                  "endAt": _value(row["end_at"]), "capacity": row["capacity"],
                  "plannedBudget": str(Decimal(str(row["planned_budget"]))),
                  "createdAt": _value(row["created_at"]), "updatedAt": _value(row["updated_at"])}
        if accepted_count is not None:
            planned, actual = Decimal(str(row["planned_budget"])), Decimal(str(actual or 0))
            result.update(acceptedGuestCount=int(accepted_count), actualBudget=str(actual),
                          remainingBudget=str(planned - actual))
        return result

    def parse_datetime(value, name):
        if not isinstance(value, str):
            raise ValidationError(f"{name} must be an ISO datetime")
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError(f"{name} must be an ISO datetime") from exc

    def parse_capacity(value):
        if isinstance(value, bool):
            raise ValidationError("capacity must be a non-negative integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("capacity must be a non-negative integer") from exc
        if parsed < 0 or str(value).strip() != str(parsed):
            raise ValidationError("capacity must be a non-negative integer")
        return parsed

    def parse_budget(value):
        if value is None or isinstance(value, bool):
            raise ValidationError("plannedBudget must be a non-negative decimal")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("plannedBudget must be a non-negative decimal") from exc
        if not parsed.is_finite() or parsed < 0:
            raise ValidationError("plannedBudget must be a non-negative decimal")
        return parsed

    def validate_interval(start, end):
        try:
            valid = start < end
        except TypeError as exc:
            raise ValidationError("startAt and endAt must use compatible ISO datetimes") from exc
        if not valid:
            raise ValidationError("startAt must be before endAt")

    @app.get("/events")
    @require_auth
    def list_events():
        allowed = {"page", "size", "name", "text", "startDate", "endDate", "sort", "direction"}
        if set(request.args) - allowed:
            raise ValidationError("Unsupported event query parameter")
        try:
            page, size = int(request.args.get("page", 1)), int(request.args.get("size", 20))
        except ValueError as exc:
            raise ValidationError("page and size must be integers") from exc
        if page < 1 or not 1 <= size <= 100:
            raise ValidationError("page must be positive and size must be between 1 and 100")
        columns = {"name": "name", "startAt": "start_at", "endAt": "end_at", "capacity": "capacity",
                   "plannedBudget": "planned_budget", "createdAt": "created_at", "updatedAt": "updated_at"}
        sort, direction = request.args.get("sort", "createdAt"), request.args.get("direction", "desc").lower()
        if sort not in columns or direction not in {"asc", "desc"}:
            raise ValidationError("Invalid event sort or direction")
        clauses, params = ["owner_id=%s"], [g.user_id]
        text = request.args.get("text", request.args.get("name"))
        if text:
            clauses.append("name ILIKE %s"); params.append("%" + text + "%")
        for key, column, operator in (("startDate", "start_at", ">="), ("endDate", "end_at", "<=")):
            if key in request.args:
                clauses.append(f"{column}{operator}%s"); params.append(parse_datetime(request.args[key], key))
        where = " AND ".join(clauses)
        total = database.fetchone(f"SELECT COUNT(*) AS total FROM events WHERE {where}", tuple(params))["total"]
        rows = database.fetchall(f"SELECT * FROM events WHERE {where} ORDER BY {columns[sort]} {direction}, id {direction} LIMIT %s OFFSET %s", tuple(params + [size, (page - 1) * size]))
        return {"items": [event_output(row) for row in rows], "total": total, "page": page, "size": size}

    @app.post("/events")
    @require_auth
    def create_event():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("Request body must be a JSON object")
        required = ["name", "startAt", "endAt", "capacity", "plannedBudget"]
        if any(key not in body for key in required):
            raise ValidationError("Missing required event fields")
        start, end = parse_datetime(body["startAt"], "startAt"), parse_datetime(body["endAt"], "endAt")
        budget, capacity = parse_budget(body["plannedBudget"]), parse_capacity(body["capacity"])
        validate_interval(start, end)
        if not isinstance(body["name"], str) or not body["name"].strip():
            raise ValidationError("name is required")
        event_id = uuid4()
        database.execute("INSERT INTO events(id,owner_id,name,description,start_at,end_at,capacity,planned_budget) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                         (event_id, g.user_id, body["name"].strip(), body.get("description"), start, end, capacity, budget))
        return {"id": str(event_id)}, 201

    @app.get("/events/<uuid:event_id>")
    @require_auth
    def get_event(event_id):
        row = event_for_owner(event_id)
        accepted = database.fetchone("SELECT COUNT(*) AS total FROM guests WHERE event_id=%s AND status='accepted'", (event_id,))["total"]
        actual = database.fetchone("SELECT COALESCE(SUM(e.amount),0) AS actual FROM expenses e JOIN budget_categories b ON b.id=e.budget_category_id WHERE b.event_id=%s", (event_id,))["actual"]
        return event_output(row, accepted, actual)

    @app.patch("/events/<uuid:event_id>")
    @require_auth
    def patch_event(event_id):
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValidationError("Request body must be a JSON object")
        allowed = {"name", "description", "capacity", "plannedBudget", "startAt", "endAt"}
        if not body:
            raise ValidationError("No updatable fields supplied")
        if set(body) - allowed:
            raise ValidationError("Unsupported event field")
        with database.transaction() as connection:
            current = event_for_owner(event_id, connection, lock=True)
            values = {"name": current["name"], "description": current["description"], "capacity": current["capacity"],
                      "planned_budget": Decimal(str(current["planned_budget"])), "start_at": current["start_at"], "end_at": current["end_at"]}
            if "name" in body:
                if not isinstance(body["name"], str) or not body["name"].strip(): raise ValidationError("name must be non-empty")
                values["name"] = body["name"].strip()
            if "description" in body:
                if body["description"] is not None and not isinstance(body["description"], str): raise ValidationError("description must be a string or null")
                values["description"] = body["description"]
            if "capacity" in body: values["capacity"] = parse_capacity(body["capacity"])
            if "plannedBudget" in body: values["planned_budget"] = parse_budget(body["plannedBudget"])
            if "startAt" in body: values["start_at"] = parse_datetime(body["startAt"], "startAt")
            if "endAt" in body: values["end_at"] = parse_datetime(body["endAt"], "endAt")
            validate_interval(values["start_at"], values["end_at"])
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total FROM guests WHERE event_id=%s AND status='accepted'", (event_id,))
                if values["capacity"] < cursor.fetchone()["total"]: raise ConflictError("capacity cannot be lower than accepted guest count")
                cursor.execute("UPDATE events SET name=%s,description=%s,capacity=%s,planned_budget=%s,start_at=%s,end_at=%s,updated_at=NOW() WHERE id=%s RETURNING *", (values["name"], values["description"], values["capacity"], values["planned_budget"], values["start_at"], values["end_at"], event_id))
                updated = cursor.fetchone()
                cursor.execute("INSERT INTO audit_logs (id,event_id,actor_user_id,resource_type,resource_id,action,details) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)", (uuid4(), event_id, g.user_id, "event", event_id, "update", json.dumps({"fields": sorted(body)})))
        return event_output(updated)

    @app.delete("/events/<uuid:event_id>")
    @require_auth
    def delete_event(event_id):
        event_for_owner(event_id)
        database.execute("DELETE FROM events WHERE id=%s", (event_id,))
        return "", 204

    @app.get("/events/<uuid:event_id>/budget")
    @require_auth
    def budget(event_id):
        row = event_for_owner(event_id)
        actual = database.fetchone("SELECT COALESCE(SUM(e.amount),0) actual FROM expenses e JOIN budget_categories b ON b.id=e.budget_category_id WHERE b.event_id=%s", (event_id,))["actual"]
        return {"planned": str(row["planned_budget"]), "actual": str(actual), "remaining": str(Decimal(row["planned_budget"]) - Decimal(actual))}

    _register_modules(app, database, settings)

    # Documentation is deliberately public: it is useful to API consumers before login.
    @app.get("/openapi.json")
    def openapi():
        return jsonify(_openapi())

    @app.get("/docs")
    def docs():
        return "<!doctype html><html><body><div id=\"swagger-ui\"></div><script src=\"https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js\"></script><script>SwaggerUIBundle({url:'/openapi.json',dom_id:'#swagger-ui'})</script></body></html>"

    return app


def _register_modules(app: Flask, db: Database, settings: Settings) -> None:
    """Register every resource blueprint with its explicitly injected dependencies."""
    from .budget_routes import budget_bp
    from .budget_service import BudgetService
    from .notifications import NotificationAuditService, PeriodicNotificationScanner, notification_audit_bp
    from .routes.guest_routes import create_guest_blueprint
    from .schedule_routes import create_schedule_blueprint
    from .services.guest_service import GuestService
    from .tasks.routes import task_bp
    from .tasks.service import TaskService
    from .vendors import create_vendor_blueprint

    services = app.extensions["services"]
    services["budget"] = BudgetService(db)
    services["task_service"] = TaskService(db)
    services["guest"] = GuestService(db)
    services["notifications"] = NotificationAuditService(db)
    app.register_blueprint(budget_bp)
    app.register_blueprint(create_guest_blueprint(services["guest"]))
    # Task handlers have no local prefix; this is their single canonical route family.
    app.register_blueprint(task_bp, url_prefix="/events/<event_id>/tasks")
    app.register_blueprint(create_schedule_blueprint(db))
    app.register_blueprint(create_vendor_blueprint(db))
    app.register_blueprint(notification_audit_bp)

    scanner = PeriodicNotificationScanner(db, enabled=settings.scheduler_enabled)
    app.extensions["notification_scanner"] = scanner
    app.extensions["periodic_notification_scanner"] = scanner
    services["notification_scanner"] = scanner
    if settings.scheduler_enabled:
        scanner.start()
    # stop() is idempotent and joins the daemon worker, avoiding shutdown races.
    atexit.register(scanner.stop)


def _openapi() -> dict:
    """Return the complete, framework-independent OpenAPI contract."""
    error = {"$ref": "#/components/schemas/Error"}
    json_body = lambda schema, required=True: {"required": required, "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}}}
    response = lambda code, schema=None, description="": {str(code): {"description": description or ("No content" if code == 204 else "Success"), **({"content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}}} if schema else {})}}
    errors = {str(code): {"description": name, "content": {"application/json": {"schema": error}}} for code, name in ((400, "Validation error"), (401, "Authentication error"), (403, "Forbidden"), (404, "Not found"), (409, "Conflict"), (500, "Internal server error"))}
    def op(summary, success=200, schema=None, body=None, parameters=()):
        value = {"summary": summary, "parameters": list(parameters), "responses": {**response(success, schema), **errors}}
        if body: value["requestBody"] = json_body(body)
        return value
    path = lambda name, desc="": {"name": name, "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}, "description": desc}
    event_id, item_id = path("event_id", "Event identifier"), path("id", "Resource identifier")
    page = {"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}
    size = {"name": "size", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100}}
    paths = {
        "/health": {"get": {"summary": "Health check", "security": [], "responses": response(200, "Health")}},
        "/docs": {"get": {"summary": "Swagger UI", "security": [], "responses": response(200, "Html")}},
        "/openapi.json": {"get": {"summary": "OpenAPI specification", "security": [], "responses": response(200, "OpenApi")}},
        "/auth/register": {"post": op("Register user", 201, "User", "Credentials")},
        "/auth/login": {"post": op("Login", 200, "Token", "Credentials")},
        "/events": {"get": op("List events", schema="EventPage", parameters=(page, size)), "post": op("Create event", 201, "Id", "EventCreate")},
        "/events/{event_id}": {"get": op("Get event", schema="Event", parameters=(event_id,)), "patch": op("Update event", schema="Event", body="EventUpdate", parameters=(event_id,)), "delete": op("Delete event", 204, parameters=(event_id,))},
        "/events/{event_id}/budget": {"get": op("Event budget summary", schema="BudgetSummary", parameters=(event_id,))},
    }
    def crud(base, singular, page_schema, create, update, resource_parameter, params=()):
        paths[base] = {"get": op(f"List {singular}", schema=page_schema, parameters=(*params, page, size)), "post": op(f"Create {singular}", 201, singular, create, params)}
        paths[base + "/{" + resource_parameter["name"] + "}"] = {"get": op(f"Get {singular}", schema=singular, parameters=(*params, resource_parameter)), "patch": op(f"Update {singular}", schema=singular, body=update, parameters=(*params, resource_parameter)), "delete": op(f"Delete {singular}", 204, parameters=(*params, resource_parameter))}
    guest_id, task_id, category_id = path("guest_id"), path("task_id"), path("category_id")
    schedule_item_id, vendor_id = path("schedule_item_id"), path("vendor_id")
    expense_id, payment_id = path("expense_id"), path("payment_id")
    crud("/events/{event_id}/guests", "Guest", "GuestPage", "GuestCreate", "GuestUpdate", guest_id, (event_id,))
    crud("/events/{event_id}/tasks", "Task", "TaskPage", "TaskCreate", "TaskUpdate", task_id, (event_id,))
    crud("/events/{event_id}/budget-categories", "BudgetCategory", "BudgetCategoryPage", "BudgetCategoryCreate", "BudgetCategoryUpdate", category_id, (event_id,))
    crud("/events/{event_id}/schedule-items", "ScheduleItem", "ScheduleItemPage", "ScheduleItemCreate", "ScheduleItemUpdate", schedule_item_id, (event_id,))
    crud("/events/{event_id}/vendors", "Vendor", "VendorPage", "VendorCreate", "VendorUpdate", vendor_id, (event_id,))
    crud("/events/{event_id}/budget-categories/{category_id}/expenses", "Expense", "ExpensePage", "ExpenseCreate", "ExpenseUpdate", expense_id, (event_id, category_id))
    crud("/events/{event_id}/vendors/{vendor_id}/payments", "VendorPayment", "VendorPaymentPage", "VendorPaymentCreate", "VendorPaymentUpdate", payment_id, (event_id, vendor_id))
    notification_id = path("notification_id")
    paths["/events/{event_id}/notifications"] = {"get": op("List notifications", schema="NotificationPage", parameters=(event_id, page, size))}
    paths["/events/{event_id}/notifications/{notification_id}"] = {"patch": op("Acknowledge notification", schema="Notification", parameters=(event_id, notification_id))}
    paths["/events/{event_id}/audit-logs"] = {"get": op("List audit logs", schema="AuditLogPage", parameters=(event_id, page, size))}
    # Authentication and documentation are the only deliberately public route families.
    paths["/auth/register"]["post"]["security"] = []
    paths["/auth/login"]["post"]["security"] = []
    query = lambda name, description="": {"name": name, "in": "query", "schema": {"type": "string"}, "description": description}
    # Resource-specific list filters/sorts accepted by the corresponding handlers.
    paths["/events/{event_id}/guests"]["get"]["parameters"] += [query(x) for x in ("name", "text", "status", "sort", "direction")]
    paths["/events/{event_id}/tasks"]["get"]["parameters"] += [query(x) for x in ("status", "priority", "sort", "order")]
    paths["/events/{event_id}/budget-categories"]["get"]["parameters"] += [query(x) for x in ("name", "sort")]
    paths["/events/{event_id}/budget-categories/{category_id}/expenses"]["get"]["parameters"] += [query(x) for x in ("sort", "startDate", "endDate")]
    paths["/events/{event_id}/schedule-items"]["get"]["parameters"] += [query(x) for x in ("sort", "text", "name", "startDate", "endDate")]
    paths["/events/{event_id}/vendors"]["get"]["parameters"] += [query(x) for x in ("category", "contract_status", "q", "sort", "order")]
    paths["/events/{event_id}/vendors/{vendor_id}/payments"]["get"]["parameters"] += [query(x) for x in ("status", "sort", "order")]
    paths["/events/{event_id}/notifications"]["get"]["parameters"] += [query(x) for x in ("sort", "direction", "kind", "sourceType", "read")]
    paths["/events/{event_id}/audit-logs"]["get"]["parameters"] += [query(x) for x in ("sort", "direction", "resourceType", "action", "startDate", "endDate")]
    schemas = _schemas()
    return {"openapi": "3.0.3", "info": {"title": "EventForge API", "version": "1.0.0", "description": "JWT-protected event planning API."}, "security": [{"bearerAuth": []}], "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}, "schemas": schemas}}


def _schemas() -> dict:
    obj = lambda properties, required=(): {"type": "object", "properties": properties, "required": list(required)}
    string = {"type": "string"}; uid = {"type": "string", "format": "uuid"}; date_time = {"type": "string", "format": "date-time"}; money = {"type": "string", "pattern": "^-?\\d+(?:\\.\\d{1,2})?$"}
    page = lambda item: obj({"items": {"type": "array", "items": {"$ref": f"#/components/schemas/{item}"}}, "total": {"type": "integer"}, "page": {"type": "integer"}, "size": {"type": "integer"}}, ("items", "total", "page", "size"))
    result = {
        "Error": obj({"timestamp": date_time, "status": {"type": "integer"}, "error": string, "message": string, "path": string}, ("timestamp", "status", "error", "message", "path")),
        "Health": obj({"status": string}, ("status",)), "Html": {"type": "string"}, "OpenApi": {"type": "object"}, "Id": obj({"id": uid}, ("id",)),
        "Credentials": obj({"email": {"type": "string", "format": "email"}, "password": {"type": "string", "minLength": 8}}, ("email", "password")), "User": obj({"id": uid, "email": {"type": "string", "format": "email"}}, ("id", "email")), "Token": obj({"accessToken": string, "tokenType": {"type": "string", "example": "Bearer"}}, ("accessToken", "tokenType")),
        "EventCreate": obj({"name": string, "description": string, "startAt": date_time, "endAt": date_time, "capacity": {"type": "integer", "minimum": 0}, "plannedBudget": money}, ("name", "startAt", "endAt", "capacity", "plannedBudget")), "EventUpdate": obj({"name": string, "description": string, "capacity": {"type": "integer", "minimum": 0}, "plannedBudget": money}), "Event": obj({"id": uid, "owner_id": uid, "name": string, "description": string, "start_at": date_time, "end_at": date_time, "capacity": {"type": "integer"}, "planned_budget": money}), "BudgetSummary": obj({"planned": money, "actual": money, "remaining": money}),
        "GuestCreate": obj({"name": string, "email": {"type": "string", "format": "email"}, "status": {"type": "string", "enum": ["invited", "accepted", "declined", "cancelled"]}}, ("name", "email")), "GuestUpdate": obj({"name": string, "email": {"type": "string", "format": "email"}, "status": {"type": "string", "enum": ["invited", "accepted", "declined", "cancelled"]}}), "Guest": obj({"id": uid, "event_id": uid, "name": string, "email": string, "status": string, "created_at": date_time, "updated_at": date_time}),
        "TaskCreate": obj({"title": string, "description": string, "due_at": date_time, "status": {"type": "string", "enum": ["todo", "in_progress", "completed", "cancelled"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "dependency_task_id": uid}, ("title",)), "TaskUpdate": obj({"title": string, "description": string, "due_at": date_time, "status": {"type": "string", "enum": ["todo", "in_progress", "completed", "cancelled"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "dependency_task_id": uid}), "Task": obj({"id": uid, "event_id": uid, "title": string, "description": string, "due_at": date_time, "status": string, "priority": string, "dependency_task_id": uid}),
        "BudgetCategoryCreate": obj({"name": string, "plannedAmount": money}, ("name", "plannedAmount")), "BudgetCategoryUpdate": obj({"name": string, "plannedAmount": money}), "BudgetCategory": obj({"id": uid, "event_id": uid, "name": string, "plannedAmount": money, "actualAmount": money, "remainingAmount": money}), "ExpenseCreate": obj({"description": string, "amount": money, "expenseDate": {"type": "string", "format": "date"}}, ("description", "amount")), "ExpenseUpdate": obj({"description": string, "amount": money, "expenseDate": {"type": "string", "format": "date"}}), "Expense": obj({"id": uid, "budget_category_id": uid, "description": string, "amount": money}),
        "ScheduleItemCreate": obj({"name": string, "description": string, "start_at": date_time, "end_at": date_time}, ("name", "start_at", "end_at")), "ScheduleItemUpdate": obj({"name": string, "description": string, "start_at": date_time, "end_at": date_time}), "ScheduleItem": obj({"id": uid, "event_id": uid, "name": string, "description": string, "start_at": date_time, "end_at": date_time}),
        "VendorCreate": obj({"name": string, "category": string, "contract_amount": money, "contract_status": string}, ("name", "contract_amount")), "VendorUpdate": obj({"name": string, "category": string, "contract_amount": money, "contract_status": string}), "Vendor": obj({"id": uid, "event_id": uid, "name": string, "contract_amount": money, "contract_status": string, "totalPaid": money, "outstanding": money}), "VendorPaymentCreate": obj({"amount": money, "payment_date": {"type": "string", "format": "date"}, "payment_method": string, "status": string}, ("amount", "payment_date")), "VendorPaymentUpdate": obj({"amount": money, "payment_date": {"type": "string", "format": "date"}, "payment_method": string, "status": string}), "VendorPayment": obj({"id": uid, "vendor_id": uid, "amount": money, "payment_date": {"type": "string", "format": "date"}, "status": string}),
        "Notification": obj({"id": uid, "eventId": uid, "kind": string, "sourceType": string, "sourceId": uid, "stateKey": string, "message": string, "readAt": date_time, "createdAt": date_time}), "AuditLog": obj({"id": uid, "eventId": uid, "actorUserId": uid, "resourceType": string, "resourceId": uid, "action": {"type": "string", "enum": ["create", "update", "delete", "status_change"]}, "details": {"type": "object"}, "createdAt": date_time}),
    }
    for item in ("Event", "Guest", "Task", "BudgetCategory", "Expense", "ScheduleItem", "Vendor", "VendorPayment", "Notification", "AuditLog"):
        result[item + "Page"] = page(item)
    return result


app = create_app() if __import__("os").environ.get("DATABASE_URL") and __import__("os").environ.get("JWT_SECRET") else None
