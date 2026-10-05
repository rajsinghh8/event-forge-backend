"""Fixtures for PostgreSQL integration tests.

These tests intentionally never replace the database layer: they require a real
PostgreSQL URL supplied by the environment and leave no rows behind per test.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "001_initial.sql"
TABLES = (
    "notifications, audit_logs, vendor_payments, vendors, expenses, "
    "budget_categories, schedule_items, guests, tasks, events, users"
)


@pytest.fixture(scope="session")
def postgres_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL integration database unavailable: DATABASE_URL is not configured")
    try:
        import psycopg  # noqa: F401
    except ImportError:
        pytest.skip("PostgreSQL integration database unavailable: psycopg is not installed")
    try:
        import psycopg
        with psycopg.connect(url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
    except Exception as exc:
        pytest.skip(f"PostgreSQL integration database unavailable: {exc}")
    return url


@pytest.fixture(scope="session")
def migrated_database(postgres_url: str) -> None:
    """Apply the project migration once, without pretending a database exists."""
    import psycopg
    with psycopg.connect(postgres_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('public.users') AS users_table")
            if cursor.fetchone()["users_table"] is None:
                cursor.execute(MIGRATION.read_text())


@pytest.fixture
def postgres(postgres_url: str, migrated_database):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(postgres_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {TABLES} CASCADE")
        connection.commit()
        yield connection
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {TABLES} CASCADE")
        connection.commit()


@pytest.fixture
def client(postgres_url: str, postgres):
    # Import only after the explicit availability check above: importing the app
    # imports psycopg-backed modules by design.
    from eventforge.app import create_app
    from eventforge.config import Settings

    app = create_app(Settings(
        database_url=postgres_url,
        jwt_secret="postgres-integration-secret",
        scheduler_enabled=False,
    ))
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client
