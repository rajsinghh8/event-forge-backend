# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2–10 Implementation | complete |
| 11–17 Verify/reports | complete with environment limitations |

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
