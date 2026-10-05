# EventForge

EventForge is a Tornado/MySQL REST API for owner-scoped event planning. Configure `.env` values, install requirements, and run `./start.sh`. APIs are at `/api`; obtain a JWT from registration or login and send `Authorization: Bearer <token>`. `/health`, `/openapi.json`, and `/docs` are public. Swagger UI supports the `bearerAuth` JWT security scheme; use **Authorize** to supply a token for protected API calls. Lists use `limit` (1–100) and `offset`, returning `{items,total,limit,offset}`. Money is represented as fixed two-decimal strings.

## Containers
`docker compose up --build` starts EventForge and MySQL 8.4.3. The application listens on port 8000.
