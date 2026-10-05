# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | complete |
| 2-7 Implementation/infra | pending |
| 8-16 Verification/reports | pending |

## Decisions
- Tornado 6.4.2, Python 3.13, MySQL 8.4.3 (`mysql:8.4.3`), one `eventforge` service on port 8000.
- Offset pagination: `limit`/`offset`, default 20, envelope `{items,total,limit,offset}`.
- JWT HS256 bearer authentication; auth and docs routes protected exactly per task; `/health` remains unauthenticated for deployment health checks.
- Layering: handlers -> `EventForgeService` -> repository -> MySQL connector; DTO serializers in models.
- Ownership policy: resources outside the authenticated owner scope return 404.
- Feature groups: core events/tasks/guests; budget/expenses; schedules/vendors/payments; notifications/audits. Shared repository/service contracts use resource operation names and Decimal string DTOs.
