# EventForge API

EventForge is an owner-scoped JSON API under `/api`. Send `Authorization: Bearer
<JWT>` on every `/api` request except registration and login. `/health`,
`/docs`, and `/openapi.json` are public operational endpoints. All times are
ISO-8601 datetimes and monetary values are nonnegative decimal values (positive
where an endpoint says so).

## Shared conventions

Collection responses have this shape:

```json
{ "items": [], "total": 0, "page": 1, "page_size": 20 }
```

Every collection accepts `page` (minimum `1`) and `page_size` (`1`--`100`).
Where supported, collection filtering uses the resource's documented `q` or
`search` text parameter, date range parameters, and `sort` plus
`order=asc|desc` for ordering. Unsupported or invalid filters, pagination, or
body fields produce `422 VALIDATION_ERROR`; malformed JSON produces `400
INVALID_JSON`. A missing resource, including a resource not owned by the caller,
is `404 NOT_FOUND`.

All error responses use the following envelope. `details` is optional and is
present only when structured error information is useful. The server also
returns the same correlation ID in `X-Correlation-ID`.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "venue is required",
    "timestamp": "2025-03-08T12:00:00+00:00",
    "correlation_id": "4ed9f83c-d8f9-4b85-86d9-2a8475749348",
    "details": { "field": "venue" }
  }
}
```

Routine validation, ownership, and business-rule errors never expose database
errors.

## Public and authentication

* `GET /health` returns process status and time.
* `GET /docs` returns the interactive documentation UI.
* `GET /openapi.json` returns the OpenAPI document.
* `POST /api/auth/register` requires `email`, an at-least-eight-character
  `password`, and `display_name`; it returns `201` with a user and token, or
  `409 EMAIL_EXISTS`.
* `POST /api/auth/login` requires `email` and `password`; it returns a user and
  token, or `401 INVALID_CREDENTIALS`.

## Events

`GET /api/events` lists the caller's events. It accepts `status`, text search
`q`, an event `date` filter, `sort`, `order=asc|desc`, and pagination. `POST
/api/events` requires `name`, `event_datetime`, and **`venue`**. It also accepts
optional `capacity`, `budget_limit`, `status` (`DRAFT`, `PLANNED`, `ACTIVE`,
`COMPLETED`, or `CANCELLED`), and `description`. `GET`, `PUT`, and `DELETE
/api/events/{event_id}` get, update, and delete an owned event; mutable event
updates retain the same required venue rule. GET includes `aggregate.planned`,
`aggregate.actual`, and `aggregate.remaining` as decimal strings. Deleting an
event returns `204` and removes its children transactionally.

### Create-event example

```http
POST /api/events
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "name": "Spring Launch",
  "event_datetime": "2025-04-20T18:00:00+00:00",
  "venue": "Harbor Hall",
  "capacity": 80,
  "budget_limit": "5000.00",
  "description": "Customer launch event"
}
```

```json
{
  "id": 42,
  "owner_id": 7,
  "name": "Spring Launch",
  "event_datetime": "2025-04-20T18:00:00+00:00",
  "venue": "Harbor Hall",
  "capacity": 80,
  "confirmed_guest_count": 0,
  "budget_limit": "5000.00",
  "status": "DRAFT",
  "description": "Customer launch event"
}
```

## Tasks and invitations

`GET`/`POST /api/events/{event_id}/tasks` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/tasks/{id}` manage tasks. Task create
requires `title` and `priority` (`LOW`, `MEDIUM`, `HIGH`, or `URGENT`); it may
include nullable `assignee`, `description`, `deadline`, and `dependency_ids`.
New tasks always start at `TODO`. Task collection filters are `status`,
`priority`, `assignee`, `deadline_from`, `deadline_to`, text `search`, `sort`,
`order`, and pagination.

The lifecycle is `TODO` → `IN_PROGRESS` or `BLOCKED`; `IN_PROGRESS` may become
`BLOCKED` or `COMPLETED`; and `BLOCKED` may resume at `IN_PROGRESS`. A completed
task cannot be reopened. Dependencies must be unique task IDs in the same event;
self and cyclic dependencies are rejected. A task can be completed only after
all prerequisites are completed.

`GET`/`POST /api/events/{event_id}/invitations` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/invitations/{id}` manage invitations.
Create requires `guest_name` and `guest_email`; `status` is one of `PENDING`,
`ACCEPTED`, `DECLINED`, or `MAYBE` and defaults to `PENDING`. Accepted RSVP
changes are transactional and maintain the event's confirmed guest count. An
acceptance that would exceed a configured event `capacity` is rejected with
`409 EVENT_CAPACITY_REACHED`.

### Capacity business-conflict example

```json
{
  "error": {
    "code": "EVENT_CAPACITY_REACHED",
    "message": "Event capacity has been reached",
    "timestamp": "2025-03-08T12:05:00+00:00",
    "correlation_id": "0cfd2c41-4a64-4fe3-901b-54bbb3ac5551"
  }
}
```

## Finance

`GET`/`POST /api/events/{event_id}/budget-categories` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/budget-categories/{id}` manage
categories. Category responses include decimal-string `planned`, `actual`, and
`remaining` totals. Deleting a category with expenses returns `409
CATEGORY_HAS_EXPENSES`; lowering its planned amount below actual spending
returns `409 CATEGORY_LIMIT_BELOW_SPEND`.

`GET`/`POST /api/events/{event_id}/expenses` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/expenses/{id}` manage expenses.
Create requires `category_id`, `description`, and positive `amount`; optional
`expenditure_at` defaults to the current time. Expense filtering includes
category, text/date/amount ranges, sort/order, and pagination. Create and
update lock the event while calculating the proposed total: an expense that
would exceed `budget_limit` is not written and returns `409
BUDGET_LIMIT_EXCEEDED`.

### Budget business-conflict example

```json
{
  "error": {
    "code": "BUDGET_LIMIT_EXCEEDED",
    "message": "Expense would exceed the event budget limit",
    "timestamp": "2025-03-08T12:10:00+00:00",
    "correlation_id": "bd4f2f1f-4fc3-46ce-b444-e2315ea1a2dc"
  }
}
```

## Schedule

`GET`/`POST /api/events/{event_id}/schedule` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/schedule/{id}` manage schedule
entries. Create requires `title`, `start_time`, and `end_time`; optional
**`description`** is a string or `null` (`details` is not a schedule field).
Schedule collection filters include `from`, `to`, text `search`, sort, and
pagination. Start must precede end, and overlapping half-open intervals are
rejected with `409 SCHEDULE_OVERLAP`.

## Vendors and payments

`GET`/`POST /api/events/{event_id}/vendors` and
`GET`/`PUT`/`DELETE /api/events/{event_id}/vendors/{id}` manage vendors. Vendor
create requires `name`, `service_type`, **`booking_status`**, and `cost`; it
accepts optional nullable **`contact_details`**. Vendor responses include
`paid_amount` and calculated decimal-string `outstanding_amount`. Vendor list
filters include `search`, `service_type`, `booking_status`, sort, and
pagination. A vendor with payments cannot be deleted (`409
VENDOR_HAS_PAYMENTS`).

`GET`/`POST /api/events/{event_id}/vendors/{vendor_id}/payments` lists or
records payments. POST requires positive `amount` and accepts `payment_at` and
`note`. Date/sort filters and pagination are supported. Paying more than the
vendor cost returns `409 PAYMENT_EXCEEDS_COST`.

## Notifications and activity

`GET /api/events/{event_id}/notifications` lists notifications and supports
`read=true|false` plus pagination. Notification state is represented by nullable
**`read_at`**: `null` means unread, while an ISO-8601 timestamp means read.
`PATCH /api/events/{event_id}/notifications/{id}` accepts `{ "read": true }`
or `{ "read": false }`, updates `read_at`, and returns the notification.

`GET /api/events/{event_id}/activity` lists immutable audit activity with
pagination.
