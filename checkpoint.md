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

## Unit status
- Operations integration: repository now implements owner-scoped schedules, vendors, and vendor-payment CRUD, payment sum aggregation, and audit writes; `EventForgeService` delegates OperationsResourceService methods; dedicated HTTP handlers/routes expose schedule-items, vendors, and nested payments. Operations rules preserve transaction/audit semantics, schedule-overlap rejection, payment caps, and Decimal string vendor aggregate views. Focused operations service tests added.
- Budget/expense integration: repository fulfills the owner/event-predicated category and expense port; facade, dedicated handlers, and routes expose budget aggregate, category CRUD, and expense CRUD. Mutations transact with audit writes and atomic 90%-threshold source dedupe; monetary DTO fields are fixed Decimal strings. Added focused budget service tests.
- Notification/audit reconciliation: `EventForgeService` now instantiates and delegates to `NotificationResourceService`; repository implements every notification/audit port method, recipient/owner predicates, and atomic task source claims via `notification_sources`. Added authenticated owner-scoped `GET /api/audit-logs`; scheduler calls the facade scan and is stopped when the main IOLoop exits. Focused tests were not run because this environment exposes no command-execution tool.
- Deploy documentation/OpenAPI: `/docs` and `/openapi.json` now use public base handlers (as does `/health`); Swagger UI persists bearer-JWT authorization. Replaced the minimal generator with a canonical OpenAPI 3.0.3 contract covering every actual route/method, aliases, request/response schemas, pagination and expense filtering, and status-specific error responses. Focused OpenAPI route tests now validate exact route/method coverage, public routes/security, aliases/audit placement, request contracts, and error envelope. Tests were not run: no command-execution tool is available in this environment.
- Final contract/security reconciliation: added authenticated, owner/event-scoped `GET /api/events/{eventId}/audit-logs`, including facade/service/repository port/OpenAPI and regression coverage. The retained `/api/audit-logs` route is explicitly documented as an optional all-owned-events list. Schedule and vendor updates/deletes now place event/owner joins in their actual `UPDATE`/`DELETE`; vendor-payment writes additionally constrain payment, vendor, event, and owner in SQL. Operations ports and fake test adapter were updated to pass scope to every mutation. The unittest suite could not be invoked because this environment provides file tools only, with no command-execution tool.
