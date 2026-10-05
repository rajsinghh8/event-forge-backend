# EventForge API

Base path: `/api`. JSON responses use ISO-8601 timestamps and decimal strings. Send `Authorization: Bearer <JWT>` except for registration, login, health and docs.

## Global behavior
Errors are `{ "error": { "code", "message", "timestamp", "correlation_id", "details"? } }`. `X-Request-ID` or `X-Correlation-ID` is echoed as `X-Correlation-ID`. Lists support `page` (>=1), `page_size` (1–100), `q`, `status`, `sort`, and `order=asc|desc`, returning `{items,total,page,page_size}`. Resource-specific filters include date ranges (`date_from`, `date_to`), task `assignee`/`priority`, expense `category_id`, and vendor `service_type`/`booking_status`.

## Auth
- `POST /auth/register` (public): `{email,password,display_name}` → `201` user and token.
- `POST /auth/login` (public): `{email,password}` → `200` same shape. Invalid credentials are `401`.

## Events
- `GET, POST /events`; `GET, PUT, DELETE /events/{event_id}`. Creation accepts `name,event_datetime,venue,capacity,budget_limit,status,description`. Event GET returns guest and budget aggregates. Deletion is `204`.

## Planning resources
- `GET, POST /events/{event_id}/tasks`; `PUT, DELETE /events/{event_id}/tasks/{task_id}`.
- `GET, POST /events/{event_id}/invitations`; `PUT, DELETE /events/{event_id}/invitations/{invitation_id}`.
- `GET, POST /events/{event_id}/budget-categories`; `PUT, DELETE /events/{event_id}/budget-categories/{category_id}`.
- `GET, POST /events/{event_id}/expenses`; `PUT, DELETE /events/{event_id}/expenses/{expense_id}`.
- `GET, POST /events/{event_id}/schedule`; `PUT, DELETE /events/{event_id}/schedule/{schedule_id}`.
- `GET, POST /events/{event_id}/vendors`; `PUT, DELETE /events/{event_id}/vendors/{vendor_id}`; `POST /events/{event_id}/vendors/{vendor_id}/payments`.
- `GET /events/{event_id}/notifications`; `PATCH /events/{event_id}/notifications/{notification_id}` marks read.
- `GET /events/{event_id}/activity` is immutable audit history.

## Conflicts
`409 CAPACITY_FULL` means accepting an invitation would exceed capacity. `409 BUDGET_EXCEEDED` means an expense would exceed the event limit. `409 SCHEDULE_OVERLAP` means `start < existing_end && end > existing_start`; back-to-back entries are valid. Task self/cyclic dependencies and completion with incomplete prerequisites are rejected. Vendor payments cannot exceed their cost; categories with expenses cannot be deleted.

See `/openapi.json` and `/docs` for machine-readable interactive documentation.
