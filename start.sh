#!/bin/sh
set -eu
python -c "import os, psycopg; c=psycopg.connect(os.environ['DATABASE_URL']); c.execute(open('migrations/001_initial.sql').read()); c.commit()"
exec gunicorn --bind 0.0.0.0:8000 eventforge.app:app
