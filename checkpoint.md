# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2–10 Implementation | complete |
| 11–17 Verify/reports | reopened: verifier gaps require live Oracle/API/docs/report/Docker remediation |
| Remediation design | complete: replace Store with a single Oracle DB-API repository layer and fully typed Bottle resource routes | 
| Remediation implementation | implemented; review/fix loop in progress |
| Remediation documentation | complete; contract review pending |
| Remediation verification/reports | pending | 

## Remediation decisions
- The executable composition root will use one Oracle DB-API persistence module, initialized at app startup with idempotent schema DDL. Every mutation runs in a commit/rollback transaction with named SQL binds; event and child reads include owner/event predicates.
- Canonical HTTP contract stays under `/api`; health/docs/spec stay public. Implement all declared event child resources and methods, including expense PUT/DELETE and notification PATCH. OpenAPI and docs mirror that exact route surface.
- Data model uses Oracle tables for users, events, tasks/task_dependencies, invitations, categories/expenses, schedule entries, vendors/payments, notifications, and activity. Application rules are enforced in the repository transaction before commit.
- Task dependency payload uses `dependency_ids` when creating/updating a task; all prerequisite records must belong to the same event, no self/cycle is permitted, and COMPLETED requires all prerequisites COMPLETED. Notifications are event-owner scoped and PATCH marks a notification read.
- Existing historical reports are evidence of a failed environment boot and will be replaced only with observed, live results after a full Oracle-backed boot.

## Decisions
- Bottle 0.13 synchronous WSGI, Python 3.13, direct `python-oracledb` with bound named SQL; Oracle owns persistence.
- Layering: `src/eventforge/{config,errors,security,validation,database,repository,services,routes,dto,openapi}.py`; thin routes, injected application service container.
- Auth: HS256 JWT; PBKDF2-SHA256 salted hashes. Owner derives solely from JWT subject.
- Collections use offset pagination `{items,total,page,page_size}` with bounded parameters.
- Independent groups/contracts: Events owns event aggregate/activity and common ownership. Tasks use statuses TODO/IN_PROGRESS/BLOCKED/COMPLETED. Invitations accepted count is maintained transactionally. Finance uses Decimal and planned/actual/remaining totals. Schedules use `[start,end)` overlap predicate. Vendor deletion conflicts if payments exist. Notifications types are deadline/invitation/overdue-task/budget-warning.
- Runtime: app :8000, Oracle compose service `oracle` image `gvenzl/oracle-free:23-slim`.
- Verification: `compileall` and unittest discovery passed (15 tests). Host boot attempt failed because Bottle is not installed. Docker pull/build verification could not run because Docker daemon is unavailable; reports record these observed limitations honestly.

## Unit status
- Event core group complete: `domain/events.py`, `event_dto.py`, `event_repository.py`, and `event_service.py` provide owner-scoped CRUD, bound Oracle SQL, aggregates, validated offset/filter DTOs, and same-transaction activity-audit protocol. Pure unit coverage is in `tests/test_event_core.py`.

## Unit status
- Auth group: complete — added PBKDF2-SHA256 password hashing, dependency-free HS256 JWT validation, typed auth service/repository boundary, public DTOs, Bottle route registration, domain error HTTP mapping, and security unit tests.
- Tasks & invitations resource group: complete. Added pure lifecycle/dependency and RSVP validation, repository ports, Oracle named-bind adapters (event counter locked for accepted RSVP), activity/notification contracts, and dependency-free unit tests.
