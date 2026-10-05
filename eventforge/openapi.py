"""Canonical OpenAPI 3.0.3 document for the HTTP routes in ``routes.py``."""
from __future__ import annotations

JSON = "application/json"
SECURITY = [{"bearerAuth": []}]


def ref(name: str) -> dict:
 return {"$ref": f"#/components/schemas/{name}"}


def response(description: str, schema: str | None = None) -> dict:
 value = {"description": description}
 if schema:
  value["content"] = {JSON: {"schema": ref(schema)}}
 return value


def request(schema: str, *, required: bool = True) -> dict:
 return {"required": required, "content": {JSON: {"schema": ref(schema)}}}


ERROR_STATUS = {"ValidationError": "422", "Unauthorized": "401", "Forbidden": "403", "NotFound": "404", "Conflict": "409", "InternalError": "500"}


def operation(summary: str, *, success: int = 200, schema: str | None = None,
              body: str | None = None, parameters: list[dict] | None = None,
              errors: tuple[str, ...] = ("Unauthorized", "ValidationError", "InternalError")) -> dict:
 responses = {str(success): response("Successful response" if success != 204 else "No content", schema)}
 responses.update({ERROR_STATUS[code]: {"$ref": f"#/components/responses/{code}"} for code in errors})
 result = {"summary": summary, "security": SECURITY, "responses": responses}
 if body:
  result["requestBody"] = request(body)
 if parameters:
  result["parameters"] = parameters
 return result


def public_operation(summary: str, *, success: int = 200, schema: str | None = None,
                     body: str | None = None, errors: tuple[str, ...] = ("ValidationError", "Conflict", "InternalError")) -> dict:
 responses = {str(success): response("Successful response", schema)}
 responses.update({ERROR_STATUS[code]: {"$ref": f"#/components/responses/{code}"} for code in errors})
 result = {"summary": summary, "responses": responses}
 if body:
  result["requestBody"] = request(body)
 return result


ID = {"name": "eventId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
CATEGORY_ID = {"name": "categoryId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
TASK_ID = {"name": "taskId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
GUEST_ID = {"name": "guestId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
SCHEDULE_ID = {"name": "scheduleItemId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
VENDOR_ID = {"name": "vendorId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
PAYMENT_ID = {"name": "paymentId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
NOTIFICATION_ID = {"name": "notificationId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}
PAGE = [
 {"name": "limit", "in": "query", "description": "Page size (1–100; default 20).", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
 {"name": "offset", "in": "query", "description": "Zero-based number of records to skip (default 0).", "schema": {"type": "integer", "minimum": 0, "default": 0}},
]
EXPENSE_FILTER = {"name": "category_id", "in": "query", "description": "Return only expenses in this budget category.", "schema": {"type": "integer", "format": "int64", "minimum": 1}}

# This list is intentionally route-derived, rather than a wish list.  It is used
# by focused tests to prevent documentation from drifting from routes.py.
PATHS = {
 "/health": ["get"], "/docs": ["get"], "/openapi.json": ["get"],
 "/api/auth/register": ["post"], "/api/auth/login": ["post"],
 "/api/events": ["get", "post"], "/api/events/{eventId}": ["get", "put", "delete"],
 "/api/events/{eventId}/tasks": ["get", "post"], "/api/events/{eventId}/tasks/{taskId}": ["get", "put", "delete"],
 "/api/events/{eventId}/guests": ["get", "post"], "/api/events/{eventId}/guests/{guestId}": ["get", "put", "delete"],
 "/api/events/{eventId}/audit-logs": ["get"],
 "/api/events/{eventId}/budget": ["get"],
 "/api/events/{eventId}/budget/categories": ["get", "post"], "/api/events/{eventId}/budget/categories/{categoryId}": ["get", "put", "delete"],
 "/api/events/{eventId}/budget-categories": ["get", "post"], "/api/events/{eventId}/budget-categories/{categoryId}": ["get", "put", "delete"],
 "/api/events/{eventId}/expenses": ["get", "post"], "/api/events/{eventId}/expenses/{expenseId}": ["get", "put", "delete"],
 "/api/events/{eventId}/schedule-items": ["get", "post"], "/api/events/{eventId}/schedule-items/{scheduleItemId}": ["get", "put", "delete"],
 "/api/events/{eventId}/vendors": ["get", "post"], "/api/events/{eventId}/vendors/{vendorId}": ["get", "put", "delete"],
 "/api/events/{eventId}/vendors/{vendorId}/payments": ["get", "post"], "/api/events/{eventId}/vendors/{vendorId}/payments/{paymentId}": ["get", "put", "delete"],
 "/api/notifications": ["get"], "/api/notifications/{notificationId}": ["get", "put", "delete"],
 "/api/audit-logs": ["get"],
}


def _singular(item: str) -> str:
 return item[:-3] + "y" if item.endswith("ies") else item[:-1] if item.endswith("s") else item


def _crud_collection(item: str, create: str, parameters: list[dict] | None = None) -> dict:
 singular = _singular(item)
 return {"get": operation(f"List {item}", schema=item + "List", parameters=parameters),
         "post": operation(f"Create {singular}", success=201, schema=singular, body=create,
                           errors=("Unauthorized", "ValidationError", "NotFound", "Conflict", "InternalError"))}


def _crud_item(item: str, update: str, parameters: list[dict]) -> dict:
 singular = _singular(item)
 return {"get": operation(f"Get {singular}", schema=singular, parameters=parameters, errors=("Unauthorized", "NotFound", "InternalError")),
         "put": operation(f"Update {singular}", schema=singular, body=update, parameters=parameters, errors=("Unauthorized", "ValidationError", "NotFound", "Conflict", "InternalError")),
         "delete": operation(f"Delete {singular}", success=204, parameters=parameters, errors=("Unauthorized", "NotFound", "Conflict", "InternalError"))}


def build_openapi() -> dict:
 paths = {
  "/health": {"get": public_operation("Health check", schema="Health", errors=("InternalError",))},
  "/docs": {"get": public_operation("Swagger UI", schema=None, errors=("InternalError",))},
  "/openapi.json": {"get": public_operation("OpenAPI document", schema="OpenApiDocument", errors=("InternalError",))},
  "/api/auth/register": {"post": public_operation("Register a user", success=201, schema="AuthResponse", body="Credentials")},
  "/api/auth/login": {"post": public_operation("Log in and obtain a bearer token", schema="AuthResponse", body="Credentials", errors=("Unauthorized", "ValidationError", "InternalError"))},
  "/api/events": _crud_collection("Events", "EventInput", PAGE),
  "/api/events/{eventId}": _crud_item("Events", "EventInput", [ID]),
  "/api/events/{eventId}/tasks": _crud_collection("Tasks", "TaskInput", [ID]),
  "/api/events/{eventId}/tasks/{taskId}": _crud_item("Tasks", "TaskInput", [ID, TASK_ID]),
  "/api/events/{eventId}/guests": _crud_collection("Guests", "GuestInput", [ID, *PAGE]),
  "/api/events/{eventId}/guests/{guestId}": _crud_item("Guests", "GuestInput", [ID, GUEST_ID]),
  "/api/events/{eventId}/audit-logs": {"get": operation("List audit logs for this owned event only", schema="AuditLogPage", parameters=[ID, *PAGE], errors=("Unauthorized", "NotFound", "InternalError"))},
  "/api/events/{eventId}/budget": {"get": operation("Get event budget aggregate", schema="BudgetAggregate", parameters=[ID], errors=("Unauthorized", "NotFound", "InternalError"))},
  "/api/events/{eventId}/budget/categories": _crud_collection("BudgetCategories", "BudgetCategoryInput", [ID]),
  "/api/events/{eventId}/budget/categories/{categoryId}": _crud_item("BudgetCategories", "BudgetCategoryUpdate", [ID, CATEGORY_ID]),
  "/api/events/{eventId}/budget-categories": _crud_collection("BudgetCategories", "BudgetCategoryInput", [ID]),
  "/api/events/{eventId}/budget-categories/{categoryId}": _crud_item("BudgetCategories", "BudgetCategoryUpdate", [ID, CATEGORY_ID]),
  "/api/events/{eventId}/expenses": _crud_collection("Expenses", "ExpenseInput", [ID, EXPENSE_FILTER]),
  "/api/events/{eventId}/expenses/{expenseId}": _crud_item("Expenses", "ExpenseUpdate", [ID, {"name": "expenseId", "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}]),
  "/api/events/{eventId}/schedule-items": _crud_collection("ScheduleItems", "ScheduleItemInput", [ID]),
  "/api/events/{eventId}/schedule-items/{scheduleItemId}": _crud_item("ScheduleItems", "ScheduleItemInput", [ID, SCHEDULE_ID]),
  "/api/events/{eventId}/vendors": _crud_collection("Vendors", "VendorInput", [ID]),
  "/api/events/{eventId}/vendors/{vendorId}": _crud_item("Vendors", "VendorInput", [ID, VENDOR_ID]),
  "/api/events/{eventId}/vendors/{vendorId}/payments": _crud_collection("VendorPayments", "VendorPaymentInput", [ID, VENDOR_ID]),
  "/api/events/{eventId}/vendors/{vendorId}/payments/{paymentId}": _crud_item("VendorPayments", "VendorPaymentInput", [ID, VENDOR_ID, PAYMENT_ID]),
  "/api/notifications": {"get": operation("List notifications", schema="NotificationPage", parameters=PAGE)},
  "/api/notifications/{notificationId}": {
   "get": operation("Get notification", schema="Notification", parameters=[NOTIFICATION_ID], errors=("Unauthorized", "NotFound", "InternalError")),
   "put": operation("Mark notification as read", schema="Notification", parameters=[NOTIFICATION_ID], errors=("Unauthorized", "NotFound", "InternalError")),
   "delete": operation("Delete notification", success=204, parameters=[NOTIFICATION_ID], errors=("Unauthorized", "NotFound", "InternalError")),
  },
  "/api/audit-logs": {"get": operation("Optional global audit list across all events owned by the authenticated caller", schema="AuditLogPage", parameters=PAGE)},
 }
 return {"openapi": "3.0.3", "info": {"title": "EventForge API", "version": "1.0.0", "description": "Owner-scoped event planning API. JSON money values are fixed two-decimal strings."},
         "paths": paths, "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT", "description": "Paste the JWT returned by register or login."}},
         "responses": _responses(), "schemas": _schemas()}}


def _responses() -> dict:
 error = {"description": "Error response", "content": {JSON: {"schema": ref("Error")}}}
 return {"ValidationError": {**error, "description": "Malformed JSON or invalid request data."}, "Unauthorized": {**error, "description": "Missing, invalid, or expired bearer token."}, "Forbidden": {**error, "description": "The caller is not allowed to access this resource."}, "NotFound": {**error, "description": "Resource not found in the caller's scope."}, "Conflict": {**error, "description": "A domain rule prevents this operation."}, "InternalError": {**error, "description": "Unexpected server error."}}


def _schemas() -> dict:
 money = {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "example": "125.00"}
 identifier = {"type": "integer", "format": "int64", "example": 1}
 opaque_id = {"type": "string", "example": "1"}
 timestamp = {"type": "string", "format": "date-time"}
 page = lambda item: {"type": "object", "required": ["items", "total", "limit", "offset"], "properties": {"items": {"type": "array", "items": ref(item)}, "total": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "offset": {"type": "integer", "minimum": 0}}}
 return {
  "OpenApiDocument": {"type": "object", "description": "The OpenAPI 3.0.3 document served by this endpoint."}, "Health": {"type": "object", "required": ["status"], "properties": {"status": {"type": "string", "example": "ok"}}},
  "Error": {"type": "object", "required": ["timestamp", "status", "error", "message", "path"], "properties": {"timestamp": timestamp, "status": {"type": "integer"}, "error": {"type": "string"}, "message": {"type": "string"}, "path": {"type": "string"}}},
  "User": {"type": "object", "required": ["id", "email"], "properties": {"id": identifier, "email": {"type": "string", "format": "email"}, "created_at": timestamp}}, "Credentials": {"type": "object", "required": ["email", "password"], "properties": {"email": {"type": "string", "format": "email"}, "password": {"type": "string", "format": "password", "minLength": 8}}}, "AuthResponse": {"type": "object", "required": ["user", "token"], "properties": {"user": ref("User"), "token": {"type": "string"}}},
  "EventInput": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "minLength": 1}, "description": {"type": "string", "nullable": True}, "start_date": {"type": "string", "format": "date", "nullable": True}, "end_date": {"type": "string", "format": "date", "nullable": True}, "capacity": {"type": "integer", "minimum": 0, "nullable": True}, "planned_budget": {**money, "nullable": True}}}, "Event": {"allOf": [ref("EventInput"), {"type": "object", "required": ["id", "owner_id"], "properties": {"id": identifier, "owner_id": identifier, "created_at": timestamp, "updated_at": timestamp}}]}, "EventsList": page("Event"),
  "TaskInput": {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string", "nullable": True}, "status": {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "cancelled"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "due_at": {**timestamp, "nullable": True}, "dependency_ids": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}}, "Task": {"allOf": [ref("TaskInput"), {"type": "object", "required": ["id", "event_id"], "properties": {"id": identifier, "event_id": identifier, "created_at": timestamp, "updated_at": timestamp}}]}, "TasksList": {"type": "array", "items": ref("Task")},
  "GuestInput": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string", "format": "email", "nullable": True}, "status": {"type": "string", "enum": ["invited", "accepted", "declined"]}}}, "Guest": {"allOf": [ref("GuestInput"), {"type": "object", "required": ["id", "event_id"], "properties": {"id": identifier, "event_id": identifier, "created_at": timestamp, "updated_at": timestamp}}]}, "GuestsList": page("Guest"),
  "BudgetCategoryInput": {"type": "object", "required": ["name", "planned_amount"], "properties": {"name": {"type": "string", "minLength": 1}, "planned_amount": money}}, "BudgetCategoryUpdate": {"type": "object", "minProperties": 1, "properties": {"name": {"type": "string", "minLength": 1}, "planned_amount": money}}, "BudgetCategory": {"allOf": [ref("BudgetCategoryInput"), {"type": "object", "required": ["id", "event_id", "actual_amount", "remaining_amount", "spent_percent"], "properties": {"id": identifier, "event_id": identifier, "actual_amount": money, "remaining_amount": money, "spent_percent": money}}]}, "BudgetCategoriesList": {"type": "array", "items": ref("BudgetCategory")}, "BudgetAggregate": {"type": "object", "required": ["event_id", "planned_amount", "actual_amount", "remaining_amount", "spent_percent", "categories"], "properties": {"event_id": identifier, "planned_amount": money, "actual_amount": money, "remaining_amount": money, "spent_percent": money, "categories": {"type": "array", "items": {"type": "object", "required": ["category", "expense_count"], "properties": {"category": ref("BudgetCategory"), "expense_count": {"type": "integer", "minimum": 0}}}}}},
  "ExpenseInput": {"type": "object", "required": ["category_id", "description", "actual_amount"], "properties": {"category_id": identifier, "description": {"type": "string", "minLength": 1}, "actual_amount": money, "incurred_at": {**timestamp, "nullable": True}}}, "ExpenseUpdate": {"type": "object", "minProperties": 1, "properties": {"category_id": identifier, "description": {"type": "string", "minLength": 1}, "actual_amount": money, "incurred_at": {**timestamp, "nullable": True}}}, "Expense": {"allOf": [ref("ExpenseInput"), {"type": "object", "required": ["id", "event_id"], "properties": {"id": identifier, "event_id": identifier}}]}, "ExpensesList": {"type": "array", "items": ref("Expense")},
  "ScheduleItemInput": {"type": "object", "required": ["title", "start_at", "end_at"], "properties": {"title": {"type": "string", "minLength": 1}, "description": {"type": "string", "nullable": True}, "start_at": timestamp, "end_at": timestamp}}, "ScheduleItem": {"allOf": [ref("ScheduleItemInput"), {"type": "object", "required": ["id", "event_id"], "properties": {"id": identifier, "event_id": identifier, "created_at": timestamp, "updated_at": timestamp}}]}, "ScheduleItemsList": {"type": "array", "items": ref("ScheduleItem")},
  "VendorInput": {"type": "object", "required": ["name", "total_amount"], "properties": {"name": {"type": "string", "minLength": 1}, "total_amount": money, "contact_name": {"type": "string", "nullable": True}, "contact_email": {"type": "string", "format": "email", "nullable": True}}}, "Vendor": {"allOf": [ref("VendorInput"), {"type": "object", "required": ["id", "event_id", "totalPaid", "outstanding"], "properties": {"id": identifier, "event_id": identifier, "totalPaid": money, "outstanding": money}}]}, "VendorsList": {"type": "array", "items": ref("Vendor")},
  "VendorPaymentInput": {"type": "object", "required": ["amount", "paid_on"], "properties": {"amount": money, "paid_on": {"type": "string", "format": "date"}, "reference": {"type": "string", "nullable": True}}}, "VendorPayment": {"allOf": [ref("VendorPaymentInput"), {"type": "object", "required": ["id", "vendor_id"], "properties": {"id": identifier, "vendor_id": identifier, "created_at": timestamp, "updated_at": timestamp}}]}, "VendorPaymentsList": {"type": "array", "items": ref("VendorPayment")},
  "Notification": {"type": "object", "required": ["id", "recipient_id", "kind", "title", "message", "is_read", "created_at"], "properties": {"id": identifier, "recipient_id": identifier, "event_id": {**identifier, "nullable": True}, "task_id": {**identifier, "nullable": True}, "kind": {"type": "string"}, "title": {"type": "string"}, "message": {"type": "string"}, "is_read": {"type": "boolean"}, "read_at": {**timestamp, "nullable": True}, "created_at": timestamp}}, "NotificationPage": page("Notification"),
  "AuditLog": {"type": "object", "required": ["id", "owner_id", "event_id", "action", "entity_type", "entity_id", "occurred_at"], "properties": {"id": identifier, "owner_id": identifier, "event_id": identifier, "action": {"type": "string"}, "entity_type": {"type": "string"}, "entity_id": identifier, "actor_id": {**identifier, "nullable": True}, "occurred_at": timestamp, "details": {"type": "object", "additionalProperties": True}}}, "AuditLogPage": page("AuditLog"),
 }
