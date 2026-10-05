# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2 Resource modules | complete; verifier repairs applied to tasks, guests, budgets/expenses, schedule, vendors/payments, notifications/audit |
| 3 Application/infra | complete; docs/spec now bearer-protected per issued-task override, registration returns a signed token, and startup waits for PostgreSQL |
| 4 Compile | passed (`python -m compileall`) |
| 5 pytest | passed: 12 tests against an isolated local PostgreSQL 17 instance (`DATABASE_URL=...127.0.0.1...`), covering auth, ownership, business rules, aggregates, audit, scanner, and docs |
| 5 Boot verification | passed: `start.sh` booted Gunicorn against isolated PostgreSQL; `/health` 200, docs unauthenticated 401, registration supplied token, authenticated docs/spec 200; app and DB stopped cleanly |
| 5 Docker verification | attempted 1/1 but cannot run: Docker CLI exists and daemon at `/var/run/docker.sock` remains unreachable, preventing pull/build/run; accurately FAIL in report |
| 6 Reports | complete: regenerated `tests-artifacts/test_results.json`, `api_test_report.xlsx`, `project_report.docx` from live HTTP probes and observed 12-test PostgreSQL result |
| Resume repairs | complete |

## Decisions
- Flask 3.1 + psycopg 3 direct SQL, Python 3.13; package `eventforge`, port 8000.
- JWT Bearer (HS256 default) / bcrypt. `/health`, register, and login are public. Resume verifier requirements deliberately override the generic deploy-contract conflict: `/docs` and `/openapi.json` require a valid Bearer token, and registration returns safe user fields plus `accessToken`/`tokenType`. Every business route uses `eventforge.security.require_auth`.
- PostgreSQL schema migration owns all 11 tables. UUIDs are generated in Python; numeric wire values are exact strings.
- Offset pagination response: `{items,total,page,size}`. Validated query sort is per-resource allowlist.
- All mutation audits use `create`, `update`, `delete`, or `status_change`; errors use `{timestamp,status,error,message,path}`.
- `PeriodicNotificationScanner` is stored in app extensions, honors `SCHEDULER_ENABLED`, starts only when enabled, and is stopped through `atexit`.

## Test coverage
- `tests/test_task_routes.py` and `tests/test_budget_routes.py` verify real Flask route JWT protection/prefix handling.
- `tests/test_postgres_integration.py` contains real PostgreSQL integration coverage for registration-token auth, docs/spec authentication, ownership 404/403, validation, capacity, task dependency/status, budget/payment caps, exact aggregates, audit rows, schedule overlap, and scanner dedupe. It ran and passed against isolated PostgreSQL 17 with migration/truncation.
