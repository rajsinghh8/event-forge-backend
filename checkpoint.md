# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2-7 Implementation/infra | complete (Dockerfile and compose existence verified) |
| 8-16 Verification/reports | complete with environment limitations |
| Remediation design | complete: specialized services are handler-facing through the facade; resource repository mutations are owner/event constrained and transactional |
| Remediation verification/reports | superseded: verifier requires live MySQL/Docker verification and contract corrections |
| Verifier remediation design | complete |
| Verifier remediation implementation | complete |
| Final live/API, report, and Docker verification | complete |

## Verifier remediation design
- Infra verification will start the supplied `mysql` compose service, then boot Tornado against it and capture real authenticated API responses. Dockerfile is pinned to `python:3.13.5-slim` and must build/run against the same MySQL network.
- Budget contract is canonical: nested `/api/events/{eventId}/budget-categories/{categoryId}/budget` plus `/expenses` CRUD, expense request/response fields are `name`, decimal `amount`, ISO `spent_on`, optional `notes`; compatibility aliases may remain only if consistently documented.
- Core contract remediation owns computed `accepted_guest_count`, strict event/task validation, page/size pagination with filters/sort allowlists, and normalized audit verbs (`create`, `update`, `delete`, `status_change`).
- Original task authentication policy wins for this remediation: `/docs` and `/openapi.json` require bearer auth (while `/health` remains public), despite the conflicting generic deploy guidance.
- Services split for delegated work: budget/routes/expense contract; core/event/task/query/audit contract; documentation/OpenAPI/auth contract. All use existing facade/repository interfaces and preserve owner/event scope.

## Remediation decisions
- `EventForgeService` is the single handler-facing facade and delegates core, budget, operations, and notification/audit methods to the specialized services using one shared MySQL repository.
- Resource mutations use repository owner/event predicates and repository transactions; audits and notification side effects share the mutation transaction.
- Contract paths: budget/categories/expenses, schedule/vendors/vendor-payments, notifications/audit logs are all owner-scoped under `/api/events/{eventId}` where relevant; scheduler invokes the facade notification scan.
- `/health` is public; `/docs` and `/openapi.json` require bearer JWT authorization per the original task policy.

## Unit status
- Operations integration: repository now implements owner-scoped schedules, vendors, and vendor-payment CRUD, payment sum aggregation, and audit writes; `EventForgeService` delegates OperationsResourceService methods; dedicated HTTP handlers/routes expose schedule-items, vendors, and nested payments. Operations rules preserve transaction/audit semantics, schedule-overlap rejection, payment caps, and Decimal string vendor aggregate views. Focused operations service tests added.
- Budget/expense integration: repository fulfills the owner/event-predicated category and expense port; facade, dedicated handlers, and routes expose budget aggregate, category CRUD, and expense CRUD. Mutations transact with audit writes and atomic 90%-threshold source dedupe; monetary DTO fields are fixed Decimal strings. Added focused budget service tests.
- Notification/audit reconciliation: `EventForgeService` now instantiates and delegates to `NotificationResourceService`; repository implements every notification/audit port method, recipient/owner predicates, and atomic task source claims via `notification_sources`. Added authenticated owner-scoped `GET /api/audit-logs`; scheduler calls the facade scan and is stopped when the main IOLoop exits. Focused tests were not run because this environment exposes no command-execution tool.
- Deploy documentation/OpenAPI: `/docs` and `/openapi.json` now use public base handlers (as does `/health`); Swagger UI persists bearer-JWT authorization. Replaced the minimal generator with a canonical OpenAPI 3.0.3 contract covering every actual route/method, aliases, request/response schemas, pagination and expense filtering, and status-specific error responses. Focused OpenAPI route tests now validate exact route/method coverage, public routes/security, aliases/audit placement, request contracts, and error envelope. Tests were not run: no command-execution tool is available in this environment.
- Final contract/security reconciliation: added authenticated, owner/event-scoped `GET /api/events/{eventId}/audit-logs`, including facade/service/repository port/OpenAPI and regression coverage. The retained `/api/audit-logs` route is explicitly documented as an optional all-owned-events list. Schedule and vendor updates/deletes now place event/owner joins in their actual `UPDATE`/`DELETE`; vendor-payment writes additionally constrain payment, vendor, event, and owner in SQL. Operations ports and fake test adapter were updated to pass scope to every mutation.

## Unit status
- Core verifier remediation: event detail now computes `accepted_guest_count` through the repository; event creation strictly validates documented event fields and task creation validates title/priority. Core audit verbs are normalized to `create`, `update`, `delete`, and `status_change`; page/size, safe sort, and core event/task/guest filtering were added with focused unit coverage. Test execution was not available in this environment.

## Final verification
- `python -m compileall eventforge tests` and `python -m unittest discover -s tests -v` passed: 19 tests.
- Supplied compose MySQL (`mysql:8.4.3`) was started and the application booted successfully with the configured MySQL/JWT settings. Observed authenticated `/docs` and `/openapi.json` 200 responses, event creation/detail (including `accepted_guest_count`), canonical category budget 200, and nested expense create/read/update 201/200/200 responses.
- `tests-artifacts/test_results.json`, `api_test_report.xlsx`, and `project_report.docx` were generated from 70 observed live HTTP checks; all are PASS (including deliberate 401 protection checks for secured endpoints).
- Docker image pulls succeeded for `mysql:8.4.3` and `python:3.13.5-slim`. Dockerfile was built with `--network host` because the isolated daemon has no default build bridge; the image ran on the compose network, `/health` returned `200 {"status":"ok"}`, and the running-state inspection returned `true`.
