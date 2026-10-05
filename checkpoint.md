# EventForge checkpoint

| Step | Status |
|---|---|
| 1 Design/scaffold | in progress |

## Decisions
- Flask 3.1 + psycopg 3 direct SQL, Python 3.13; package `eventforge`, port 8000.
- JWT Bearer (HS256 default) / bcrypt; only auth register/login public. Per requested exception, docs/spec routes stay JWT-protected (health is public for deployment verification).
- PostgreSQL schema migration owns all 11 tables. UUIDs are generated in Python; numeric wire values are exact strings.
- Offset pagination response: `{items,total,page,size}`. Validated query sort is per-resource allowlist.
- Independent service groups: task; guest; budget+expense; schedule; vendor+payment; notification+audit. All use shared injected Database/Repositories conventions and migration contracts.
