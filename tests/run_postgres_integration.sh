#!/bin/sh
# Run the test suite against an already-running PostgreSQL instance.
# This script deliberately does not create or start any services.  The pytest
# fixtures own migration and per-test TRUNCATE cleanup after the database is up.
set -eu

: "${DATABASE_URL:?DATABASE_URL must point to the PostgreSQL instance to verify}"
: "${POSTGRES_WAIT_SECONDS:=30}"

python - <<'PY'
import os
import time

import psycopg

url = os.environ["DATABASE_URL"]
deadline = time.monotonic() + int(os.environ["POSTGRES_WAIT_SECONDS"])
last_error = None
while time.monotonic() < deadline:
    try:
        with psycopg.connect(url) as connection:
            connection.execute("SELECT 1")
        break
    except psycopg.OperationalError as error:
        last_error = error
        time.sleep(1)
else:
    raise SystemExit(f"PostgreSQL did not become ready: {last_error}")
PY

exec python -m pytest -q tests "$@"
