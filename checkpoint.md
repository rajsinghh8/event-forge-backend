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
