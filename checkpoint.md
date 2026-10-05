# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2 Resource modules | complete; verifier repairs applied to tasks, guests, budgets/expenses, schedule, vendors/payments, notifications/audit |
| 3 Application/infra | complete; guest/task wiring, scanner lifecycle, public docs/spec and complete OpenAPI added |
| 4 Compile | passed (`python -m compileall`) |
| 5 pytest | passed with 4 focused tests; 6 PostgreSQL integration cases honestly skipped because no reachable `DATABASE_URL`/PostgreSQL service exists |
| 5 Boot verification | attempted 3/3 via `start.sh`; all failed at migration with `psycopg.OperationalError`: connection to `127.0.0.1:5432` refused |
| 5 Public live probes | passed: gunicorn served `/health`, `/docs`, `/openapi.json` as 200 and unauthenticated `/events` as 401; factory probe observed 44/44 non-public routes reject missing Bearer tokens with 401 |
| 5 Docker verification | failed/skipped honestly: Docker client is installed but daemon at `/var/run/docker.sock` is unavailable, so pull/build/run cannot execute |
| 6 Reports | complete: `tests-artifacts/test_results.json`, `api_test_report.xlsx`, `project_report.docx` based only on observed results |

## Decisions
- Flask 3.1 + psycopg 3 direct SQL, Python 3.13; package `eventforge`, port 8000.
- JWT Bearer (HS256 default) / bcrypt. Register/login, `/health`, `/docs`, and `/openapi.json` are public; every business route uses `eventforge.security.require_auth`.
- PostgreSQL schema migration owns all 11 tables. UUIDs are generated in Python; numeric wire values are exact strings.
- Offset pagination response: `{items,total,page,size}`. Validated query sort is per-resource allowlist.
- All mutation audits use `create`, `update`, `delete`, or `status_change`; errors use `{timestamp,status,error,message,path}`.
- `PeriodicNotificationScanner` is stored in app extensions, honors `SCHEDULER_ENABLED`, starts only when enabled, and is stopped through `atexit`.

## Test coverage
- `tests/test_task_routes.py` and `tests/test_budget_routes.py` verify real Flask route JWT protection/prefix handling.
- `tests/test_postgres_integration.py` contains real PostgreSQL integration coverage for auth, ownership 404/403, validation, capacity, task dependency/status, budget/payment caps, exact aggregates, audit rows, schedule overlap, scanner dedupe, and docs/spec. It requires a reachable `DATABASE_URL` and performs migration/truncation; it was not falsely passed without that dependency.
