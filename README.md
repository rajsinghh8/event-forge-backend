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

Run `python -m compileall eventforge` and `python -m pytest -q` for the normal suite.

For the real PostgreSQL integration suite, start PostgreSQL separately (for example,
`docker compose up -d postgres`) and then run:

```sh
DATABASE_URL=postgresql://eventforge:eventforge@localhost:5432/eventforge \
  sh tests/run_postgres_integration.sh
```

The verification script starts no services. It waits for the supplied database; the
existing pytest fixtures then apply the migration when needed and truncate tables
before and after each integration test. Generated observed verification artifacts
remain under `tests-artifacts/`.
