# EventForge API

EventForge is a JSON API for owner-scoped event planning. The canonical API
base path is **`/api`**. In particular, authentication endpoints are
`/api/auth/*`, not `/auth/*`. The public operational endpoints (`/health`,
`/docs`, and `/openapi.json`) do not have the `/api` prefix.

All request and response bodies are JSON unless a `204 No Content` response is
specified. Timestamps are ISO-8601/RFC 3339 strings (for example,
`2025-06-14T18:00:00Z`); date-only fields use `YYYY-MM-DD`; and monetary
values are decimal strings with two fractional digits. IDs are opaque IDs
shown as integers below.

## Authentication, ownership, and common responses

Except for the public endpoints and registration/login, send:

```http
Authorization: Bearer <JWT>
```

The JWT is issued by the auth endpoints. Its subject determines the current
user; clients cannot supply an owner ID. Events and all nested resources are
visible only to the event owner. Missing, malformed, expired, or invalid
Bearer tokens produce `401`.

Successful collection responses always use this envelope:

```json
{
  "items": [{ "id": 42 }],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

All collections accept `page` (integer, >= 1) and `page_size` (integer,
1--100). Unless noted otherwise they also accept `q` (case-insensitive text
search), `status`, `sort`, and `order` (`asc` or `desc`). `date_from` and
`date_to` are inclusive ISO dates/timestamps appropriate to the resource;
they filter an event's `event_datetime`, a task's `deadline`, an expense's
`occurred_on`, a schedule entry's `start_time`, a payment's `payment_at`, or
an activity/notification `created_at`. A bad query or body field returns
`422 VALIDATION_ERROR`.

Errors have the following shape. `X-Request-ID` or `X-Correlation-ID`, when
sent, is echoed as `X-Correlation-ID` and is also included in the error.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "amount must be positive",
    "timestamp": "2025-06-01T09:30:00Z",
    "correlation_id": "client-request-17",
    "details": {}
  }
}
```

Common statuses are `200 OK`, `201 Created`, `204 No Content`, `400
INVALID_JSON`, `401 AUTHENTICATION_REQUIRED`/`INVALID_TOKEN`, `404 NOT_FOUND`,
`409` (documented per operation below), `422 VALIDATION_ERROR`, and `500
INTERNAL_ERROR`. A nested-resource `404` is also returned when the resource
does not belong to the specified owned event.

## Auth

### `POST /api/auth/register` (public)

Create an account and receive a JWT.

```json
{ "email": "alex@example.com", "password": "long-secret", "display_name": "Alex Lee" }
```

`201 Created`:

```json
{
  "user": { "id": 1, "email": "alex@example.com", "display_name": "Alex Lee", "created_at": "2025-06-01T09:00:00Z" },
  "token": "eyJ..."
}
```

`422` is returned for an invalid email, a password shorter than eight
characters, or invalid display name. `409 EMAIL_EXISTS` is returned when the
email is already registered. There are no other conflict conditions.

### `POST /api/auth/login` (public)

```json
{ "email": "alex@example.com", "password": "long-secret" }
```

`200 OK` returns the same `user` and `token` shape as registration. `401
INVALID_CREDENTIALS` is returned for an incorrect email/password pair; `422`
covers malformed required fields. There is no `409` condition.

## Events

An event has `id`, `name`, `event_datetime`, `venue` (nullable), `capacity`
(nullable positive integer), `budget_limit` (decimal string), `status`,
`description` (nullable), `confirmed_guest_count`, `created_at`, and
`updated_at`. Valid event statuses are `DRAFT`, `PLANNED`, `ACTIVE`,
`COMPLETED`, and `CANCELLED`.

### `GET /api/events`

List the caller's events. Filters: common pagination/search/sort plus
`status`, `date_from`, and `date_to` (event datetime).

`200 OK` example: `{"items":[{"id":10,"name":"Summer Gala","event_datetime":"2025-06-14T18:00:00Z","status":"PLANNED"}],"total":1,"page":1,"page_size":20}`.

No conflict condition applies (`409` is never returned by this read).

### `POST /api/events`

```json
{
  "name": "Summer Gala", "event_datetime": "2025-06-14T18:00:00Z",
  "venue": "Riverside Hall", "capacity": 120, "budget_limit": "10000.00",
  "status": "PLANNED", "description": "Annual benefit"
}
```

`201 Created` returns the created event, for example
`{"id":10,"name":"Summer Gala","event_datetime":"2025-06-14T18:00:00Z","venue":"Riverside Hall","capacity":120,"budget_limit":"10000.00","status":"PLANNED","confirmed_guest_count":0,"created_at":"2025-06-01T09:10:00Z"}`.

`name` and `event_datetime` are required. `422` covers invalid timestamps,
capacity, money, or status. There is no `409` condition.

### `GET /api/events/{event_id}`

`200 OK` returns the event plus aggregate totals:

```json
{
  "id": 10, "name": "Summer Gala", "budget_limit": "10000.00",
  "confirmed_guest_count": 25,
  "aggregate": { "attendee_count": 25, "remaining_capacity": 95,
    "planned": "8500.00", "actual": "2750.00", "remaining": "7250.00" }
}
```

`404` applies to an absent/not-owned event. There is no `409` condition.

### `PUT /api/events/{event_id}`

Send one or more mutable event fields (`name`, `event_datetime`, `venue`,
`capacity`, `budget_limit`, `status`, `description`), for example:

```json
{ "venue": "New Riverside Hall", "budget_limit": "12500.00", "status": "ACTIVE" }
```

`200 OK` returns the updated event. `422` applies to invalid values (including
capacity below confirmed attendees). `409` is not used by this endpoint.

### `DELETE /api/events/{event_id}`

`204 No Content` deletes the event and its nested planning data. `404` applies
to an absent/not-owned event. There is no `409` condition.

## Tasks

Task fields are `id`, `event_id`, `title`, `description` (nullable),
`status` (`TODO`, `IN_PROGRESS`, `BLOCKED`, or `COMPLETED`), `priority`,
`assignee`, `deadline` (nullable timestamp), `dependency_ids` (array of task
IDs), `created_at`, and `updated_at`.

### `GET /api/events/{event_id}/tasks`

List tasks. Along with common filters, use `assignee`, `priority`, `status`,
`date_from`, and `date_to` (deadline). `200 OK` example:

```json
{"items":[{"id":31,"title":"Confirm catering","status":"TODO","priority":"HIGH","assignee":"Alex","deadline":"2025-06-05T17:00:00Z","dependency_ids":[30]}],"total":1,"page":1,"page_size":20}
```

There is no `409` condition.

### `POST /api/events/{event_id}/tasks`

```json
{
  "title": "Confirm catering", "description": "Get signed quote",
  "status": "TODO", "priority": "HIGH", "assignee": "Alex",
  "deadline": "2025-06-05T17:00:00Z", "dependency_ids": [30]
}
```

`201 Created` returns the task. `dependency_ids` must name tasks in the same
event. `409 TASK_DEPENDENCY_CONFLICT` is returned for self-dependency, a
cycle, or dependencies outside the event. `422` covers invalid status/date or
fields.

### `PUT /api/events/{event_id}/tasks/{task_id}`

Send replacement/updated task fields, including `dependency_ids` when changing
prerequisites:

```json
{ "status": "COMPLETED", "dependency_ids": [30] }
```

`200 OK` returns the updated task. `409 TASK_DEPENDENCY_CONFLICT` covers a
self/cyclic/cross-event dependency; `409 INCOMPLETE_DEPENDENCIES` is returned
when attempting `COMPLETED` before every prerequisite is completed. `422`
covers invalid field values.

### `DELETE /api/events/{event_id}/tasks/{task_id}`

`204 No Content` on deletion. `409 TASK_DEPENDENCY_CONFLICT` is returned if
another task still depends on this task; remove or change that dependency
first. `404` applies when absent/not owned.

## Invitations

Invitation fields are `id`, `event_id`, `guest_name`, `guest_email`, `status`
(`PENDING`, `ACCEPTED`, `DECLINED`, `MAYBE`), optional `plus_ones`, optional
`note`, `created_at`, and `updated_at`.

### `GET /api/events/{event_id}/invitations`

List invitations. Use common filters plus `status`, `date_from`, and
`date_to` (creation time). `200 OK` example:

```json
{"items":[{"id":51,"guest_name":"Sam Guest","guest_email":"sam@example.com","status":"ACCEPTED"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `POST /api/events/{event_id}/invitations`

```json
{ "guest_name": "Sam Guest", "guest_email": "sam@example.com", "status": "PENDING", "plus_ones": 1, "note": "Vegetarian" }
```

`201 Created` returns the invitation. `409 CAPACITY_FULL` is returned if a
newly accepted invitation (including its accepted guests) exceeds event
capacity. `422` covers email, status, and field validation.

### `PUT /api/events/{event_id}/invitations/{invitation_id}`

```json
{ "status": "ACCEPTED", "plus_ones": 1 }
```

`200 OK` returns the updated invitation and updates the event's accepted guest
count transactionally. `409 CAPACITY_FULL` is returned if the transition or
plus-one change would exceed capacity. `422` covers invalid fields/status.

### `DELETE /api/events/{event_id}/invitations/{invitation_id}`

`204 No Content` deletes the invitation and adjusts accepted count if needed.
There is no `409` condition.

## Budget categories and expenses

Category responses include `id`, `event_id`, `name`, `planned_amount`, and
computed decimal-string totals `planned`, `actual`, and `remaining`, plus
creation/update timestamps. Expense fields are `id`, `event_id`,
`category_id`, `description`, `amount`, `occurred_on`, `created_at`, and
`updated_at`.

### `GET /api/events/{event_id}/budget-categories`

List categories and their totals. Use common filters and `date_from`/
`date_to` (creation time). `200 OK` example:

```json
{"items":[{"id":61,"name":"Catering","planned_amount":"4000.00","planned":"4000.00","actual":"1250.00","remaining":"2750.00"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `POST /api/events/{event_id}/budget-categories`

```json
{ "name": "Catering", "planned_amount": "4000.00" }
```

`201 Created` returns the category with zero actual spending and its totals.
`409 CATEGORY_NAME_EXISTS` is returned for a duplicate category name in the
event. `422` covers invalid money/name.

### `PUT /api/events/{event_id}/budget-categories/{category_id}`

```json
{ "name": "Food and beverage", "planned_amount": "4500.00" }
```

`200 OK` returns the recalculated category totals. `409 CATEGORY_NAME_EXISTS`
applies to a duplicate name; `409 CATEGORY_LIMIT_BELOW_SPEND` applies when the
new planned amount is below actual expense total. `422` covers invalid input.

### `DELETE /api/events/{event_id}/budget-categories/{category_id}`

`204 No Content` deletes an empty category. `409 CATEGORY_HAS_EXPENSES` is
returned when expenses remain in the category. Delete or move those expenses
first.

### `GET /api/events/{event_id}/expenses`

List expenses. Filters: common pagination/search/sort, `category_id`, and
`date_from`/`date_to` for `occurred_on`. `200 OK` example:

```json
{"items":[{"id":71,"category_id":61,"description":"Deposit","amount":"1250.00","occurred_on":"2025-05-20"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `POST /api/events/{event_id}/expenses`

```json
{ "category_id": 61, "description": "Catering deposit", "amount": "1250.00", "occurred_on": "2025-05-20" }
```

`201 Created` returns the expense; category/event totals are recalculated.
`409 BUDGET_EXCEEDED` is returned when the event budget limit would be
exceeded; `409 CATEGORY_BUDGET_EXCEEDED` applies when the category planned
amount would be exceeded. `422` covers unknown/malformed field values.

### `PUT /api/events/{event_id}/expenses/{expense_id}`

```json
{ "category_id": 61, "description": "Final catering deposit", "amount": "1500.00", "occurred_on": "2025-05-21" }
```

`200 OK` returns the updated expense and recalculated totals. It returns `409
BUDGET_EXCEEDED` or `409 CATEGORY_BUDGET_EXCEEDED` if the resulting totals are
too high. `422` covers invalid input.

### `DELETE /api/events/{event_id}/expenses/{expense_id}`

`204 No Content` deletes the expense and recalculates totals. There is no
`409` condition.

## Schedule

Schedule entries have `id`, `event_id`, `title`, `description` (nullable),
`start_time`, `end_time`, `location` (nullable), and timestamps. Intervals are
half-open: `[start_time, end_time)`.

### `GET /api/events/{event_id}/schedule`

Use common filters plus `date_from`/`date_to` (start time). `200 OK` example:

```json
{"items":[{"id":81,"title":"Doors open","start_time":"2025-06-14T18:00:00Z","end_time":"2025-06-14T19:00:00Z","location":"Lobby"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `POST /api/events/{event_id}/schedule`

```json
{ "title": "Doors open", "start_time": "2025-06-14T18:00:00Z", "end_time": "2025-06-14T19:00:00Z", "location": "Lobby" }
```

`201 Created` returns the entry. `409 SCHEDULE_OVERLAP` is returned when
`start_time < existing_end_time && end_time > existing_start_time`; adjacent
entries are valid. `422` includes `start_time >= end_time`.

### `PUT /api/events/{event_id}/schedule/{schedule_id}`

Send updated schedule fields; `200 OK` returns the entry. The same `409
SCHEDULE_OVERLAP` and `422` time-order rules apply.

### `DELETE /api/events/{event_id}/schedule/{schedule_id}`

`204 No Content` on deletion. There is no `409` condition.

## Vendors and payments

Vendor fields are `id`, `event_id`, `name`, `service_type`, `contact_name`,
`contact_email`, `contact_phone`, `cost`, `booking_status`, `booking_reference`
(nullable), `booking_date` (nullable), `notes` (nullable), `paid_amount`,
`outstanding_amount`, and timestamps. `cost`, `paid_amount`, and
`outstanding_amount` are decimal strings. Payment fields are `id`, `event_id`,
`vendor_id`, `amount`, `payment_at`, `note`, and `created_at`.

### `GET /api/events/{event_id}/vendors`

List vendors. Filters: common parameters, `service_type`, `booking_status`,
and `date_from`/`date_to` (booking date). `200 OK` example:

```json
{"items":[{"id":91,"name":"Fine Catering","service_type":"CATERING","contact_email":"bookings@fine.example","cost":"4000.00","booking_status":"CONFIRMED","paid_amount":"1000.00","outstanding_amount":"3000.00"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `POST /api/events/{event_id}/vendors`

```json
{
  "name": "Fine Catering", "service_type": "CATERING", "contact_name": "Jamie Doe",
  "contact_email": "bookings@fine.example", "contact_phone": "+1-555-0100",
  "cost": "4000.00", "booking_status": "CONFIRMED",
  "booking_reference": "FC-204", "booking_date": "2025-04-10", "notes": "Vegetarian menu"
}
```

`201 Created` returns the vendor with `paid_amount: "0.00"` and calculated
`outstanding_amount`. `409 VENDOR_NAME_EXISTS` is returned for a duplicate
vendor/service-type booking in the event. `422` covers contact, booking, and
money validation.

### `PUT /api/events/{event_id}/vendors/{vendor_id}`

Send mutable vendor booking/contact/cost fields; `200 OK` returns the vendor.
`409 VENDOR_NAME_EXISTS` applies to a duplicate booking identity and `409
VENDOR_COST_BELOW_PAYMENTS` applies if a new cost is below payments already
recorded. `422` covers invalid values.

### `DELETE /api/events/{event_id}/vendors/{vendor_id}`

`204 No Content` deletes a vendor with no payments. `409 VENDOR_HAS_PAYMENTS`
is returned when payments exist.

### `GET /api/events/{event_id}/vendors/{vendor_id}/payments`

List a vendor's payments. Use common pagination/sort plus `date_from` and
`date_to` (payment time). `200 OK` example:

```json
{"items":[{"id":101,"vendor_id":91,"amount":"1000.00","payment_at":"2025-05-01T12:00:00Z","note":"Deposit"}],"total":1,"page":1,"page_size":20}
```

There is no `409` condition.

### `POST /api/events/{event_id}/vendors/{vendor_id}/payments`

```json
{ "amount": "1000.00", "payment_at": "2025-05-01T12:00:00Z", "note": "Deposit" }
```

`201 Created` returns the payment and recalculated vendor `paid_amount` /
`outstanding_amount`. `409 PAYMENT_EXCEEDS_COST` is returned when cumulative
payments would exceed vendor cost. `422` covers non-positive amount or bad
datetime.

## Notifications and activity

### `GET /api/events/{event_id}/notifications`

List owner-scoped notifications. Notification fields are `id`, `event_id`,
`type` (`deadline`, `invitation`, `overdue-task`, or `budget-warning`),
`message`, `read` (boolean), `read_at` (nullable), `created_at`, and optional
`resource_id`. Filters: common pagination/sort plus `read` (`true`/`false`),
`type`, `date_from`, and `date_to` (creation time).

`200 OK` example:

```json
{"items":[{"id":111,"type":"deadline","message":"Confirm catering is due tomorrow","read":false,"read_at":null,"created_at":"2025-06-04T09:00:00Z"}],"total":1,"page":1,"page_size":20}
```

No `409` condition applies.

### `PATCH /api/events/{event_id}/notifications/{notification_id}`

Mark a notification's read status. The normal use is:

```json
{ "read": true }
```

`200 OK` example: `{"id":111,"read":true,"read_at":"2025-06-04T10:00:00Z"}`.
`422` applies unless `read` is boolean. Notifications may only be marked read,
not edited or deleted. There is no `409` condition.

### `GET /api/events/{event_id}/activity`

Return immutable audit history. Items contain `id`, `event_id`,
`actor_user_id`, `action`, `details`, and `created_at`. Use common pagination,
`action`, `date_from`, and `date_to` (creation time). `200 OK` example:

```json
{"items":[{"id":121,"action":"EXPENSE_CREATED","actor_user_id":1,"details":{"expense_id":71},"created_at":"2025-05-20T08:30:00Z"}],"total":1,"page":1,"page_size":20}
```

Activity is read-only and has no `409` condition.

## Public operational endpoints

### `GET /health` (public)

`200 OK` indicates the process is healthy:

```json
{ "status": "ok", "time": "2025-06-01T09:00:00Z" }
```

This endpoint has no request body, authentication, pagination, or `409`
condition.

### `GET /openapi.json` (public)

`200 OK` returns the OpenAPI 3 document for this canonical surface, for
example `{"openapi":"3.0.3","info":{"title":"EventForge API","version":"1.0.0"},"paths":{...}}`.
There is no `409` condition.

### `GET /docs` (public)

`200 OK` returns the interactive API documentation UI, backed by
`/openapi.json`. It has no request body, authentication, pagination, or `409`
condition.
