# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2–10 Implementation | in progress |
| 11–17 Verify/reports | pending |

## Decisions
- Bottle 0.13 synchronous WSGI, Python 3.13, direct `python-oracledb` with bound named SQL; Oracle owns persistence.
- Layering: `src/eventforge/{config,errors,security,validation,database,repository,services,routes,dto,openapi}.py`; thin routes, injected application service container.
- Auth: HS256 JWT; PBKDF2-SHA256 salted hashes. Owner derives solely from JWT subject.
- Collections use offset pagination `{items,total,page,page_size}` with bounded parameters.
- Independent groups/contracts: Events owns event aggregate/activity and common ownership. Tasks use statuses TODO/IN_PROGRESS/BLOCKED/COMPLETED. Invitations accepted count is maintained transactionally. Finance uses Decimal and planned/actual/remaining totals. Schedules use `[start,end)` overlap predicate. Vendor deletion conflicts if payments exist. Notifications types are deadline/invitation/overdue-task/budget-warning.
- Runtime: app :8000, Oracle compose service `oracle` image `gvenzl/oracle-free:23-slim`.
