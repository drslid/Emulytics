"""Apply versioned runs migrations explicitly: python -m app.migrate."""

import hashlib
import os
from pathlib import Path

import psycopg


def migrate(dsn: str) -> None:
    if not dsn:
        raise ValueError("EMULYTIX_DATABASE_URL is required")
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        connection.execute("SET LOCAL statement_timeout = '30s'")
        connection.execute("SELECT pg_advisory_xact_lock(783514901)")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        for migration in sorted((Path(__file__).parent / "migrations").glob("*.sql")):
            content = migration.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            applied = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version = %s", (migration.name,)
            ).fetchone()
            if applied:
                if applied[0] != checksum:
                    raise RuntimeError(f"Applied migration changed: {migration.name}")
                continue
            connection.execute(content.decode())
            connection.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                (migration.name, checksum),
            )


if __name__ == "__main__":
    database_url = os.getenv("EMULYTIX_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("Set EMULYTIX_DATABASE_URL before running migrations.")
    try:
        migrate(database_url)
    except psycopg.Error:
        raise SystemExit("Runs migration failed. Check PostgreSQL availability and schema.") from None
    print("Runs database migrations applied.")
