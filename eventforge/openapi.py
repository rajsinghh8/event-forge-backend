"""OpenAPI contract for EventForge's HTTP surface.

Documentation routes are deliberately authenticated: only ``/health`` and the
registration/login endpoints are public.
"""
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


def request(schema: str) -> dict:
 return {"required": True, "content": {JSON: {"schema": ref(schema)}}}


ERROR_STATUS = {"ValidationError": "422", "Unauthorized": "401", "NotFound": "404", "Conflict": "409", "InternalError": "500"}


def operation(summary: str, *, success: int = 200, schema: str | None = None,
              body: str | None = None, parameters: list[dict] | None = None,
              errors: tuple[str, ...] = ("Unauthorized", "ValidationError", "InternalError")) -> dict:
 responses = {str(success): response("No content" if success == 204 else "Successful response", schema)}
 responses.update({ERROR_STATUS[error]: {"$ref": f"#/components/responses/{error}"} for error in errors})
 result = {"summary": summary, "security": SECURITY, "responses": responses}
 if body:
  result["requestBody"] = request(body)
 if parameters:
  result["parameters"] = parameters
 return result


def public_operation(summary: str, *, success: int = 200, schema: str | None = None,
                     body: str | None = None, errors: tuple[str, ...] = ("ValidationError", "Conflict", "InternalError")) -> dict:
 responses = {str(success): response("Successful response", schema)}
 responses.update({ERROR_STATUS[error]: {"$ref": f"#/components/responses/{error}"} for error in errors})
 result = {"summary": summary, "responses": responses}
 if body:
  result["requestBody"] = request(body)
 return result


def path_id(name: str) -> dict:
 return {"name": name, "in": "path", "required": True, "schema": {"type": "integer", "format": "int64", "minimum": 1}}


ID = path_id("eventId")
CATEGORY_ID = path_id("categoryId")
EXPENSE_ID = path_id("expenseId")
TASK_ID = path_id("taskId")
GUEST_ID = path_id("guestId")
SCHEDULE_ID = path_id("scheduleItemId")
VENDOR_ID = path_id("vendorId")
PAYMENT_ID = path_id("paymentId")
NOTIFICATION_ID = path_id("notificationId")
PAGE = [
 {"name": "page", "in": "query", "description": "One-based page number; must be an integer of at least 1.", "schema": {"type": "integer", "minimum": 1, "default": 1}},
 {"name": "size", "in": "query", "description": "Page size; must be an integer from 1 through 100.", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}},
]
FILTER = {"name": "filter", "in": "query", "description": "Resource-specific strict filter value. Unsupported filters are rejected.", "schema": {"type": "string"}}
SORT = {"name": "sort", "in": "query", "description": "Resource-specific allowlisted sort field; prefix with '-' for descending order.", "schema": {"type": "string"}}
EXPENSE_FILTER = {"name": "category_id", "in": "query", "description": "Legacy event-level expense list filter: category identifier.", "schema": {"type": "integer", "format": "int64", "minimum": 1}}

# Kept route-derived, including the backwards-compatible budget aliases.  The
# nested category paths are the canonical expense contract.
PATHS = {
 "/health": ["get"], "/docs": ["get"], "/openapi.json": ["get"],
 "/api/auth/register": ["post"], "/api/auth/login": ["post"],
 "/api/events": ["get", "post"], "/api/events/{eventId}": ["get", "put", "delete"],
 "/api/events/{eventId}/tasks": ["get", "post"], "/api/events/{eventId}/tasks/{taskId}": ["get", "put", "delete"],
 "/api/events/{eventId}/guests": ["get", "post"], "/api/events/{eventId}/guests/{guestId}": ["get", "put", "delete"],
 "/api/events/{eventId}/audit-logs": ["get"], "/api/events/{eventId}/budget": ["get"],
 "/api/events/{eventId}/budget/categories": ["get", "post"], "/api/events/{eventId}/budget/categories/{categoryId}": ["get", "put", "delete"],
 "/api/events/{eventId}/budget-categories": ["get", "post"], "/api/events/{eventId}/budget-categories/{categoryId}": ["get", "put", "delete"],
 "/api/events/{eventId}/budget-categories/{categoryId}/budget": ["get"],
 "/api/events/{eventId}/budget-categories/{categoryId}/expenses": ["get", "post"],
 "/api/events/{eventId}/budget-categories/{categoryId}/expenses/{expenseId}": ["get", "put", "delete"],
 "/api/events/{eventId}/expenses": ["get", "post"], "/api/events/{eventId}/expenses/{expenseId}": ["get", "put", "delete"],
 "/api/events/{eventId}/schedule-items": ["get", "post"], "/api/events/{eventId}/schedule-items/{scheduleItemId}": ["get", "put", "delete"],
 "/api/events/{eventId}/vendors": ["get", "post"], "/api/events/{eventId}/vendors/{vendorId}": ["get", "put", "delete"],
 "/api/events/{eventId}/vendors/{vendorId}/payments": ["get", "post"], "/api/events/{eventId}/vendors/{vendorId}/payments/{paymentId}": ["get", "put", "delete"],
 "/api/notifications": ["get"], "/api/notifications/{notificationId}": ["get", "put", "delete"], "/api/audit-logs": ["get"],
}


def _singular(item: str) -> str:
 return item[:-3] + "y" if item.endswith("ies") else item[:-1] if item.endswith("s") else item


def _collection(item: str, create: str, parameters: list[dict] | None = None) -> dict:
 singular = _singular(item)
 return {"get": operation(f"List {item}", schema=item + "List", parameters=parameters),
         "post": operation(f"Create {singular}", success=201, schema=singular, body=create,
                           errors=("Unauthorized", "ValidationError", "NotFound", "Conflict", "InternalError"))}


def _item(item: str, update: str, parameters: list[dict]) -> dict:
 singular = _singular(item)
 return {"get": operation(f"Get {singular}", schema=singular, parameters=parameters, errors=("Unauthorized", "NotFound", "InternalError")),
         "put": operation(f"Update {singular}", schema=singular, body=update, parameters=parameters, errors=("Unauthorized", "ValidationError", "NotFound", "Conflict", "InternalError")),
         "delete": operation(f"Delete {singular}", success=204, parameters=parameters, errors=("Unauthorized", "NotFound", "Conflict", "InternalError"))}


def build_openapi() -> dict:
 list_query = [*PAGE, FILTER, SORT]
 paths = {
  "/health": {"get": public_operation("Health check", schema="Health", errors=("InternalError",))},
  # These are protected operations even though Swagger's bootstrap page is HTML.
  "/docs": {"get": operation("Swagger UI", errors=("Unauthorized", "InternalError"))},
  "/openapi.json": {"get": operation("OpenAPI document", schema="OpenApiDocument", errors=("Unauthorized", "InternalError"))},
  "/api/auth/register": {"post": public_operation("Register a user", success=201, schema="AuthResponse", body="Credentials")},
  "/api/auth/login": {"post": public_operation("Log in and obtain a bearer token", schema="AuthResponse", body="Credentials", errors=("Unauthorized", "ValidationError", "InternalError"))},
  "/api/events": _collection("Events", "EventInput", list_query),
  "/api/events/{eventId}": _item("Events", "EventInput", [ID]),
  "/api/events/{eventId}/tasks": _collection("Tasks", "TaskInput", [ID, *list_query]),
  "/api/events/{eventId}/tasks/{taskId}": _item("Tasks", "TaskInput", [ID, TASK_ID]),
  "/api/events/{eventId}/guests": _collection("Guests", "GuestInput", [ID, *list_query]),
  "/api/events/{eventId}/guests/{guestId}": _item("Guests", "GuestInput", [ID, GUEST_ID]),
  "/api/events/{eventId}/audit-logs": {"get": operation("List audit logs for this owned event", schema="AuditLogPage", parameters=[ID, *list_query], errors=("Unauthorized", "NotFound", "InternalError"))},
  "/api/events/{eventId}/budget": {"get": operation("Get event budget aggregate", schema="BudgetAggregate", parameters=[ID], errors=("Unauthorized", "NotFound", "InternalError"))},
  "/api/events/{eventId}/budget/categories": _collection("BudgetCategories", "BudgetCategoryInput", [ID, *list_query]),
  "/api/events/{eventId}/budget/categories/{categoryId}": _item("BudgetCategories", "BudgetCategoryUpdate", [ID, CATEGORY_ID]),
  "/api/events/{eventId}/budget-categories": _collection("BudgetCategories", "BudgetCategoryInput", [ID, *list_query]),
  "/api/events/{eventId}/budget-categories/{categoryId}": _item("BudgetCategories", "BudgetCategoryUpdate", [ID, CATEGORY_ID]),
  "/api/events/{eventId}/budget-categories/{categoryId}/budget": {"get": operation("Get budget category aggregate", schema="BudgetCategory", parameters=[ID, CATEGORY_ID], errors=("Unauthorized", "NotFound", "InternalError"))},
  "/api/events/{eventId}/budget-categories/{categoryId}/expenses": _collection("Expenses", "ExpenseInput", [ID, CATEGORY_ID, *list_query]),
  "/api/events/{eventId}/budget-categories/{categoryId}/expenses/{expenseId}": _item("Expenses", "ExpenseUpdate", [ID, CATEGORY_ID, EXPENSE_ID]),
  "/api/events/{eventId}/expenses": _collection("Expenses", "LegacyExpenseInput", [ID, EXPENSE_FILTER, *PAGE, SORT]),
  "/api/events/{eventId}/expenses/{expenseId}": _item("Expenses", "LegacyExpenseUpdate", [ID, EXPENSE_ID]),
  "/api/events/{eventId}/schedule-items": _collection("ScheduleItems", "ScheduleItemInput", [ID, *list_query]),
  "/api/events/{eventId}/schedule-items/{scheduleItemId}": _item("ScheduleItems", "ScheduleItemInput", [ID, SCHEDULE_ID]),
  "/api/events/{eventId}/vendors": _collection("Vendors", "VendorInput", [ID, *list_query]),
  "/api/events/{eventId}/vendors/{vendorId}": _item("Vendors", "VendorInput", [ID, VENDOR_ID]),
  "/api/events/{eventId}/vendors/{vendorId}/payments": _collection("VendorPayments", "VendorPaymentInput", [ID, VENDOR_ID, *list_query]),
  "/api/events/{eventId}/vendors/{vendorId}/payments/{paymentId}": _item("VendorPayments", "VendorPaymentInput", [ID, VENDOR_ID, PAYMENT_ID]),
  "/api/notifications": {"get": operation("List notifications", schema="NotificationPage", parameters=list_query)},
  "/api/notifications/{notificationId}": _item("Notifications", "NotificationUpdate", [NOTIFICATION_ID]),
  "/api/audit-logs": {"get": operation("List audit records across events owned by the caller", schema="AuditLogPage", parameters=list_query)},
 }
 return {"openapi": "3.0.3", "info": {"title": "EventForge API", "version": "1.0.0", "description": "Owner-scoped event planning API. Monetary values are fixed two-decimal strings."}, "paths": paths,
         "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}, "responses": _responses(), "schemas": _schemas()}}


def _responses() -> dict:
 error = {"description": "Error response", "content": {JSON: {"schema": ref("Error")}}}
 return {"ValidationError": {**error, "description": "Malformed JSON, invalid query parameter, or invalid request data."}, "Unauthorized": {**error, "description": "Missing, invalid, or expired bearer token."}, "NotFound": {**error, "description": "Resource not found in the caller's scope."}, "Conflict": {**error, "description": "A domain rule prevents this operation."}, "InternalError": {**error, "description": "Unexpected server error."}}


def _schemas() -> dict:
 money = {"type": "string", "pattern": r"^-?\d+\.\d{2}$", "example": "125.00"}
 identifier = {"type": "integer", "format": "int64", "example": 1}
 timestamp = {"type": "string", "format": "date-time"}
 page = lambda item: {"type": "object", "required": ["items", "total", "page", "size"], "properties": {"items": {"type": "array", "items": ref(item)}, "total": {"type": "integer", "minimum": 0}, "page": {"type": "integer", "minimum": 1}, "size": {"type": "integer", "minimum": 1, "maximum": 100}}}
 return {
  "OpenApiDocument": {"type": "object"}, "Health": {"type": "object", "required": ["status"], "properties": {"status": {"type": "string", "example": "ok"}}},
  "Error": {"type": "object", "required": ["timestamp", "status", "error", "message", "path"], "properties": {"timestamp": timestamp, "status": {"type": "integer"}, "error": {"type": "string"}, "message": {"type": "string"}, "path": {"type": "string"}}},
  "User": {"type": "object", "required": ["id", "email"], "properties": {"id": identifier, "email": {"type": "string", "format": "email"}, "created_at": timestamp}}, "Credentials": {"type": "object", "required": ["email", "password"], "properties": {"email": {"type": "string", "format": "email"}, "password": {"type": "string", "format": "password", "minLength": 8}}}, "AuthResponse": {"type": "object", "required": ["user", "token"], "properties": {"user": ref("User"), "token": {"type": "string"}}},
  "EventInput": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string", "minLength": 1}, "description": {"type": "string", "nullable": True}, "start_date": {"type": "string", "format": "date", "nullable": True}, "end_date": {"type": "string", "format": "date", "nullable": True}, "capacity": {"type": "integer", "minimum": 0, "nullable": True}, "planned_budget": {**money, "nullable": True}}}, "Event": {"allOf": [ref("EventInput"), {"type": "object", "required": ["id", "owner_id", "accepted_guest_count"], "properties": {"id": identifier, "owner_id": identifier, "accepted_guest_count": {"type": "integer", "minimum": 0, "description": "Computed count of guests with accepted status."}, "created_at": timestamp, "updated_at": timestamp}}]}, "EventsList": page("Event"),
  "TaskInput": {"type": "object", "properties": {"title": {"type": "string"}, "description": {"type": "string", "nullable": True}, "status": {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "cancelled"]}, "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "due_at": {**timestamp, "nullable": True}, "dependency_ids": {"type": "array", "items": identifier, "uniqueItems": True}}}, "Task": {"allOf": [ref("TaskInput"), {"type": "object", "properties": {"id": identifier, "event_id": identifier}}]}, "TasksList": page("Task"),
  "GuestInput": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string", "format": "email", "nullable": True}, "status": {"type": "string", "enum": ["invited", "accepted", "declined"]}}}, "Guest": {"allOf": [ref("GuestInput"), {"type": "object", "properties": {"id": identifier, "event_id": identifier}}]}, "GuestsList": page("Guest"),
  "BudgetCategoryInput": {"type": "object", "required": ["name", "planned_amount"], "properties": {"name": {"type": "string", "minLength": 1}, "planned_amount": money}}, "BudgetCategoryUpdate": {"type": "object", "minProperties": 1, "properties": {"name": {"type": "string", "minLength": 1}, "planned_amount": money}}, "BudgetCategory": {"allOf": [ref("BudgetCategoryInput"), {"type": "object", "properties": {"id": identifier, "event_id": identifier, "actual_amount": money, "remaining_amount": money, "spent_percent": money}}]}, "BudgetCategoriesList": page("BudgetCategory"), "BudgetAggregate": {"type": "object", "properties": {"event_id": identifier, "planned_amount": money, "actual_amount": money, "remaining_amount": money, "spent_percent": money, "categories": {"type": "array", "items": ref("BudgetCategory")}}},
  "ExpenseInput": {"type": "object", "required": ["name", "amount", "spent_on"], "properties": {"name": {"type": "string", "minLength": 1}, "amount": money, "spent_on": {"type": "string", "format": "date"}, "notes": {"type": "string", "nullable": True}}}, "ExpenseUpdate": {"type": "object", "minProperties": 1, "properties": {"name": {"type": "string", "minLength": 1}, "amount": money, "spent_on": {"type": "string", "format": "date"}, "notes": {"type": "string", "nullable": True}}}, "Expense": {"allOf": [ref("ExpenseInput"), {"type": "object", "required": ["id", "event_id", "category_id"], "properties": {"id": identifier, "event_id": identifier, "category_id": identifier}}]}, "ExpensesList": page("Expense"),
  "LegacyExpenseInput": {"type": "object", "required": ["category_id", "description", "actual_amount"], "properties": {"category_id": identifier, "description": {"type": "string"}, "actual_amount": money, "incurred_at": {**timestamp, "nullable": True}}}, "LegacyExpenseUpdate": {"type": "object", "minProperties": 1, "properties": {"category_id": identifier, "description": {"type": "string"}, "actual_amount": money, "incurred_at": {**timestamp, "nullable": True}}},
  "ScheduleItemInput": {"type": "object", "properties": {"title": {"type": "string"}, "start_at": timestamp, "end_at": timestamp}}, "ScheduleItem": {"allOf": [ref("ScheduleItemInput"), {"type": "object", "properties": {"id": identifier, "event_id": identifier}}]}, "ScheduleItemsList": page("ScheduleItem"),
  "VendorInput": {"type": "object", "properties": {"name": {"type": "string"}, "total_amount": money}}, "Vendor": {"allOf": [ref("VendorInput"), {"type": "object", "properties": {"id": identifier, "event_id": identifier}}]}, "VendorsList": page("Vendor"), "VendorPaymentInput": {"type": "object", "properties": {"amount": money, "paid_on": {"type": "string", "format": "date"}}}, "VendorPayment": {"allOf": [ref("VendorPaymentInput"), {"type": "object", "properties": {"id": identifier, "vendor_id": identifier}}]}, "VendorPaymentsList": page("VendorPayment"),
  "Notification": {"type": "object", "properties": {"id": identifier, "is_read": {"type": "boolean"}}}, "NotificationUpdate": {"type": "object", "properties": {"is_read": {"type": "boolean"}}}, "NotificationsList": page("Notification"), "NotificationPage": page("Notification"),
  "AuditLog": {"type": "object", "properties": {"id": identifier, "event_id": identifier, "action": {"type": "string"}, "occurred_at": timestamp}}, "AuditLogPage": page("AuditLog"),
 }
