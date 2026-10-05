# EventForge

EventForge is a Flask REST API for event planning, using PostgreSQL and direct psycopg SQL.

## Run

```sh
cp .env.example .env
# Set DATABASE_URL and JWT_SECRET
./start.sh
```

The API listens on port 8000. `/health` is public for container health checks. Registration and login are public; all business routes and API documentation require `Authorization: Bearer <token>`.

Apply `migrations/001_initial.sql` before starting if not using `start.sh`.

## Verification

Run `python -m compileall eventforge` and `python -m pytest -q`. Generated observed verification artifacts are under `tests-artifacts/`.
