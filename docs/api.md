# EventForge API

EventForge is an owner-scoped JSON API. The API base path is `/api`; `/health`,
`/docs`, and `/openapi.json` are public operational endpoints. All other
endpoints require `Authorization: Bearer <JWT>`, except registration and login.
The executable OpenAPI contract at `/openapi.json` is authoritative.

## Shared conventions

Collections return `{ "items": [], "total": 0, "page": 1, "page_size": 20 }`.
Every collection supports `page` (minimum 1) and `page_size` (1--100). Invalid
body fields and pagination are `422 VALIDATION_ERROR`; malformed JSON is `400
INVALID_JSON`; absent or non-owned nested records are `404 NOT_FOUND`. Monetary
amounts are nonnegative decimal values (or positive where explicitly required)
and timestamps are ISO-8601 datetimes.

Error responses use `{"error":{"code":"...","message":"..."}}`; routine
validation, ownership, and business conflicts never expose database errors.

## Public and authentication

* `GET /health` returns `200` with process status and time.
* `GET /docs` returns `200` HTML API documentation.
* `GET /openapi.json` returns `200` OpenAPI 3.0 JSON.
* `POST /api/auth/register` accepts `email`, `password` (at least eight
  characters), and `display_name`; it returns `201` user/token or `409
  EMAIL_EXISTS`.
* `POST /api/auth/login` accepts `email` and `password`; it returns `200`
  user/token or `401 INVALID_CREDENTIALS`.

## Events

`GET /api/events` lists owned events and accepts the optional `status` filter
(`DRAFT`, `PLANNED`, `ACTIVE`, `COMPLETED`, or `CANCELLED`). `POST /api/events`
creates an event from `name`, `event_datetime`, and optional `venue`, `capacity`,
`budget_limit`, `status`, and `description`; invalid status is `422`.

`GET`, `PUT`, and `DELETE /api/events/{event_id}` get, update, or delete an
owned event. PUT accepts the same mutable event fields and validates status and
capacity. GET returns an `aggregate` with decimal-string `planned`, `actual`,
and `remaining` values. DELETE returns `204` and transactionally removes every
child record (including dependencies and payments), so no child rows remain.

## Tasks and invitations

`GET`/`POST /api/events/{event_id}/tasks` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/tasks/{id}` manage tasks. Task status
is one of `TODO`, `IN_PROGRESS`, `BLOCKED`, or `COMPLETED`; create accepts
`title`, optional `description`, `deadline`, `status`, and `dependency_ids`.
Dependencies must be integer task IDs in the same event. Self, cyclic, and
cross-event dependencies return `409 TASK_DEPENDENCY_CONFLICT`. A task cannot
be marked complete before its prerequisites (`409 INCOMPLETE_DEPENDENCIES`),
and a completed task cannot be reopened (`409 TASK_COMPLETED_IMMUTABLE`). A
task with dependents cannot be deleted.

`GET`/`POST /api/events/{event_id}/invitations` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/invitations/{id}` manage invitations.
Invitation create accepts `guest_name`, `guest_email`, and `status`
(`PENDING`, `ACCEPTED`, `DECLINED`, `MAYBE`).

## Finance

`GET`/`POST /api/events/{event_id}/budget-categories` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/budget-categories/{id}` manage
categories. A category response, including list items, always includes
`planned`, `actual`, and `remaining` decimal-string totals. Delete returns
`409 CATEGORY_HAS_EXPENSES` when it still has expenses; lowering planned below
actual returns `409 CATEGORY_LIMIT_BELOW_SPEND`.

`GET`/`POST /api/events/{event_id}/expenses` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/expenses/{id}` manage expenses.
Create requires `category_id`, `description`, and positive `amount`; optional
`expenditure_at` defaults to the current time. PUT validates category ownership
and applies the expense mutation atomically.

## Schedule

`GET`/`POST /api/events/{event_id}/schedule` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/schedule/{id}` manage schedule
entries. GET accepts optional `from` and `to` ISO datetimes; `from` after `to`
is `422`. POST accepts `title`, `start_time`, `end_time`, and optional
`details`; start must precede end. Create and update reject overlapping
half-open intervals with `409 SCHEDULE_OVERLAP`. Schedule data is listed by
start time.

## Vendors and payments

`GET`/`POST /api/events/{event_id}/vendors` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/vendors/{id}` manage vendor fields
`name`, `service_type`, `contact_name`, `contact_email`, `booking_reference`,
and `cost`. Vendor GET responses include calculated `outstanding_amount`
(`cost - paid_amount`). Vendors with payments cannot be deleted (`409
VENDOR_HAS_PAYMENTS`).

`GET`/`POST /api/events/{event_id}/vendors/{vendor_id}/payments` lists or
records payments. POST requires positive `amount`, with optional `payment_at`
and `note`; cumulative payment above vendor cost is `409
PAYMENT_EXCEEDS_COST`.

## Notifications and activity

`GET /api/events/{event_id}/notifications` lists notifications. `PATCH
/api/events/{event_id}/notifications/{id}` accepts documented `{ "read": true
}` and backward-compatible `{ "is_read": true }`; either must be boolean and
the returned notification includes boolean `read`.

`GET /api/events/{event_id}/activity` lists immutable audit activity.
