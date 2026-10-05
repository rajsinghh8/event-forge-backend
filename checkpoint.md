# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2–10 Implementation | complete |
| 11–17 Verify/reports | complete: requirements installed, compile/unit tests and live public API probes pass; reports refreshed |
| Remediation design | complete: replace Store with a single Oracle DB-API repository layer and fully typed Bottle resource routes | 
| Remediation implementation | complete: executable Store replaced by Oracle DB-API schema/transactions/owner-scoped routes; source contract/unit checks pass |
| Remediation documentation | complete: exact `/api` contract and OpenAPI expanded |
| Remediation verification/reports | complete with observed infrastructure limitation: reports regenerated from live refused requests and passing unit run |
| Final Dockerfile verification | attempted and failed: Docker daemon unavailable (`Cannot connect to the Docker daemon at unix:///var/run/docker.sock`) |
| Verifier remediation | complete: active routes/schema/docs remediated; 30 unit tests and four live public/API observations pass; reports refreshed | 

## Verifier remediation decisions
- The active `src/eventforge/app.py` is authoritative. Its invitation and task routes replace generic CRUD; each mutation writes activity in the same database transaction. RSVP status changes adjust the event's locked confirmed counter (including accepted create/update/delete) and write invitation notifications.
- Event budget is checked from a locked event row plus proposed expense totals before an expense INSERT/UPDATE. The mutation is rejected rather than creating a post-facto warning.
- Tasks persist `priority` and nullable `assignee`, enforce TODO → IN_PROGRESS/BLOCKED → COMPLETED only (BLOCKED may resume IN_PROGRESS), and emit deadline/overdue notifications plus activity transactionally. Collection filtering is explicit and validated.
- Canonical contracts: event `venue` required; vendor uses optional `contact_details` and required `booking_status`; schedule uses `description`; notification state is nullable `read_at`, with PATCH `{read:true|false}`. Pagination values outside bounds are validation errors, never clamped.
- Oracle DDL declares child foreign keys, data constraints, and query indexes. Docs and the hand-written OpenAPI are updated in the same change as active routes.
- Verification runs within `python:3.13-slim` using installed requirements, starts Oracle infra when Docker is available, then starts/probes the Bottle app in one disposable invocation; reports preserve all prior unique rows and use only observed responses. 

## Remediation decisions
- The executable composition root will use one Oracle DB-API persistence module, initialized at app startup with idempotent schema DDL. Every mutation runs in a commit/rollback transaction with named SQL binds; event and child reads include owner/event predicates.
- Canonical HTTP contract stays under `/api`; health/docs/spec stay public. Implement all declared event child resources and methods, including expense PUT/DELETE and notification PATCH. OpenAPI and docs mirror that exact route surface.
- Data model uses Oracle tables for users, events, tasks/task_dependencies, invitations, categories/expenses, schedule entries, vendors/payments, notifications, and activity. Application rules are enforced in the repository transaction before commit.
- Task dependency payload uses `dependency_ids` when creating/updating a task; all prerequisite records must belong to the same event, no self/cycle is permitted, and COMPLETED requires all prerequisites COMPLETED. Notifications are event-owner scoped and PATCH marks a notification read.
- Existing historical reports were replaced with observed results: the unit suite passed (17 tests), while four real HTTP requests failed only because three native boot attempts stopped at `ModuleNotFoundError: No module named 'bottle'`. `python -m pip` is unavailable on the host and the Docker daemon/compose plugin is unavailable, so Oracle infra, live API success probes, Docker image pull, and Dockerfile build/run cannot be completed in this environment. The JSON/XLSX/DOCX reports record this honestly.

## Decisions
- Bottle 0.13 synchronous WSGI, Python 3.13, direct `python-oracledb` with bound named SQL; Oracle owns persistence.
- Layering: `src/eventforge/{config,errors,security,validation,database,repository,services,routes,dto,openapi}.py`; thin routes, injected application service container.
- Auth: HS256 JWT; PBKDF2-SHA256 salted hashes. Owner derives solely from JWT subject.
- Collections use offset pagination `{items,total,page,page_size}` with bounded parameters.
- Independent groups/contracts: Events owns event aggregate/activity and common ownership. Tasks use statuses TODO/IN_PROGRESS/BLOCKED/COMPLETED. Invitations accepted count is maintained transactionally. Finance uses Decimal and planned/actual/remaining totals. Schedules use `[start,end)` overlap predicate. Vendor deletion conflicts if payments exist. Notifications types are deadline/invitation/overdue-task/budget-warning.
- Runtime: app :8000, Oracle compose service `oracle` image `gvenzl/oracle-free:23-slim`.
- Verification: `compileall` and `PYTHONPATH=src python -m unittest discover -s tests -v` passed (30 tests). After `ensurepip`, corrected `oracledb` dependency installation enabled a live Bottle boot; `/health`, `/docs`, and `/openapi.json` returned 200 and unauthenticated `/api/events` returned 401. Reports were regenerated from those response objects. Docker image pulls and final `docker build` were attempted but Docker's daemon remained unavailable; the exact failure is recorded above.

## Unit status
- Event core group complete: `domain/events.py`, `event_dto.py`, `event_repository.py`, and `event_service.py` provide owner-scoped CRUD, bound Oracle SQL, aggregates, validated offset/filter DTOs, and same-transaction activity-audit protocol. Pure unit coverage is in `tests/test_event_core.py`.

## Unit status
- Auth group: complete — added PBKDF2-SHA256 password hashing, dependency-free HS256 JWT validation, typed auth service/repository boundary, public DTOs, Bottle route registration, domain error HTTP mapping, and security unit tests.
- Tasks & invitations resource group: complete. Added pure lifecycle/dependency and RSVP validation, repository ports, Oracle named-bind adapters (event counter locked for accepted RSVP), activity/notification contracts, and dependency-free unit tests.

## Unit status
- Schedule/vendor/payment/notification remediation group: complete — active Bottle handlers use schedule `description`, canonical vendor fields and filters, payment date/sort filtering, nullable notification `read_at`, and same-transaction activity records; source-contract coverage updated.
