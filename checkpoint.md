# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2-7 Implementation/infra | complete (Dockerfile and compose existence verified) |
| 8-16 Verification/reports | complete with environment limitations |
| Remediation design | in progress: route all resources through specialized services; repository implements their owner-scoped transactional contracts | 

## Remediation decisions
- `EventForgeService` is the single handler-facing facade and delegates core, budget, operations, and notification/audit methods to the specialized services using one shared MySQL repository.
- Resource mutations use repository owner/event predicates and repository transactions; audits and notification side effects share the mutation transaction.
- Contract paths: budget/categories/expenses, schedule/vendors/vendor-payments, notifications/audit logs are all owner-scoped under `/api/events/{eventId}` where relevant; scheduler invokes the facade notification scan.
- Public deployment routes are `/health`, `/docs`, and `/openapi.json`; Swagger uses bearer JWT authorization.

## Verification
- `python -m pip install -r requirements.txt`, `python -m compileall eventforge tests`, and `python -m unittest discover -s tests`: passed (7 tests).
- Live boot was issued 3/3 times and failed because no MySQL was available at `127.0.0.1:3306`; Docker daemon was unavailable, so compose infra could not be started.
- Report artifacts exist in `tests-artifacts/`.
- Dockerfile final build/run verification attempted and failed before build because the Docker daemon is unavailable (`Cannot connect to the Docker daemon`).


## Decisions
- Tornado 6.4.2, Python 3.13, MySQL 8.4.3 (`mysql:8.4.3`), one `eventforge` service on port 8000.
- Offset pagination: `limit`/`offset`, default 20, envelope `{items,total,limit,offset}`.
- JWT HS256 bearer authentication; auth and docs routes protected exactly per task; `/health` remains unauthenticated for deployment health checks.
- Layering: handlers -> `EventForgeService` -> repository -> MySQL connector; DTO serializers in models.
- Ownership policy: resources outside the authenticated owner scope return 404.
- Feature groups: core events/tasks/guests; budget/expenses; schedules/vendors/payments; notifications/audits. Shared repository/service contracts use resource operation names and Decimal string DTOs.

## Unit status
- Core event/task/guest feature complete: `eventforge/resource_services/core.py` defines injected `CoreResourceService` and its local `CoreRepository` Protocol. It provides owner-scoped Event/Task/Guest CRUD, pagination, Decimal-safe DTO normalization, task dependency/cycle/delete and status-transition rules, accepted-capacity enforcement, plus repository audit/notification calls.

## Unit status
- Notifications/audits: implemented `eventforge/resource_services/notifications.py` with recipient/owner scoped service contracts, pagination validation, ownership-safe not-found handling, and atomic source-state de-duplicated due-task scan coordination.
- Budget/expenses: implemented `eventforge/resource_services/budget.py` with typed category and expense CRUD contracts, Decimal-string aggregate DTOs, planned-versus-actual guards, repository auditing, and atomic de-duplicated 90% spending notifications.
- Schedules/vendors/payments: implemented `eventforge/resource_services/operations.py` with owner-scoped, transactional CRUD contracts; schedule time ordering/overlap checks; Decimal-string vendor totals with paid/outstanding values; payment-total guards; and mutation auditing.
