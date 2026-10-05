#!/bin/sh
set -eu

# Resolve project-relative migration and import paths when launched by an
# absolute path during host or container verification.
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# Compose can start this container before PostgreSQL accepts connections.  Wait
# here and apply the one-time bootstrap migration only to an empty database.
python - <<'PY'
import os
import time
from pathlib import Path

import psycopg

url = os.environ["DATABASE_URL"]
last_error = None
for _ in range(30):
    try:
        with psycopg.connect(url, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('public.users')")
                if cursor.fetchone()[0] is None:
                    cursor.execute(Path("migrations/001_initial.sql").read_text())
        break
    except psycopg.OperationalError as error:
        last_error = error
        time.sleep(1)
else:
    raise SystemExit(f"PostgreSQL was not ready after 30 seconds: {last_error}")
PY

exec gunicorn --bind 0.0.0.0:8000 eventforge.app:app
