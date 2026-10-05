# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete; resumed verifier repair plan recorded |\n| Repair group implementation | in progress: task, guest, budget, schedule, vendor/payment, notifications/audit dispatched independently |\n| Factory/OpenAPI/integration tests | pending after resource repairs |\n| Verification/reports/Docker | pending live rerun |\n\n## Resume repair contracts\n- All resource mutation audits use `create`, `update`, `delete`, or `status_change`; error responses use the five-key envelope supplied by app-level handlers.\n- All business routes require `eventforge.security.require_auth`; `/health`, `/docs`, and `/openapi.json` are public. Task routes are registered only at `/events/<event_id>/tasks`.\n- Nested ownership means missing resource is 404; an existing event owned by another user is 403. Shared persistence calls must use the active transaction cursor/connection.\n- Shared API contract remains Flask/Postgres/JWT on port 8000; tests will run against PostgreSQL and generate observed live-request artifacts.
| 2 Resource modules | complete (tasks, guests, budgets, schedule, vendors, notifications/audit) |
| 3 Application/infra | complete |
| 4 Compile | passed |
| 5 pytest/boot/Docker verification | blocked by host: Python has no pip/dependencies and Docker daemon unavailable; 3 actual boot attempts captured psycopg missing |
| 6 Reports | complete: tests-artifacts/api_test_report.xlsx and project_report.docx |

## Decisions
- Flask 3.1 + psycopg 3 direct SQL, Python 3.13; package `eventforge`, port 8000.
- JWT Bearer (HS256 default) / bcrypt; only auth register/login public. Per requested exception, docs/spec routes stay JWT-protected (health is public for deployment verification).
- PostgreSQL schema migration owns all 11 tables. UUIDs are generated in Python; numeric wire values are exact strings.
- Offset pagination response: `{items,total,page,size}`. Validated query sort is per-resource allowlist.
- Independent service groups: task; guest; budget+expense; schedule; vendor+payment; notification+audit. All use shared injected Database/Repositories conventions and migration contracts.

## Unit status
- Vendor + VendorPayment: implemented `eventforge/vendors.py` with injected-DB repository/service, `vendor_bp`/blueprint factory, owner-scoped vendor and payment CRUD/list endpoints, decimal-string projections, safe pagination, payment cap locking, deletion restrictions, and transactional audit rows.

## Task resource status
- Complete: added `eventforge/tasks` repository, service, and authenticated blueprint routes. Supports event-scoped task CRUD, pagination/filter/sort, dependency and completion validation, owner checks, and transactional audit-log writes.

## Unit updates
- Notification + AuditLog: implemented `eventforge/notifications.py` with owner-scoped list/acknowledgement and audit list routes, validated pagination/filtering/safe sorting, advisory-lock deduplicated due/overdue/90%-budget scanner, and a stoppable once-per-minute scanner adapter. The app factory must register `notification_audit_bp` and inject the shared database/service as documented in the module.

## Unit status
- Guests resource complete: added `eventforge/repositories/guest_repository.py`, `eventforge/services/guest_service.py`, and `eventforge/routes/guest_routes.py`. The blueprint factory must be registered by the shared application factory.

## Unit status
- BudgetCategory + Expense: implemented `budget_service.py` and `budget_routes.py`; includes owner-scoped CRUD, exact Decimal money, category projections, cap/unique/empty-delete rules, safe list filtering/sorting/pagination, transactional audit records, and deduplicated 90% threshold notifications.

## Unit status
- ScheduleItem: implemented `schedule_repository.py`, `schedule_service.py`, and `schedule_routes.py`. The injected-Database blueprint factory `create_schedule_blueprint` (alias `schedule_blueprint`) must be registered by the shared app factory. It provides owner-scoped CRUD, datetime/pagination/filter/sort validation, half-open overlap enforcement, explicit transactional audit writes, and 404-versus-403 event ownership checks.
