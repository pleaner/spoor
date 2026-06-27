"""Connection + schema bootstrap for the spoor file→DB spike.

Thin psycopg2 layer — no ORM. The spike's whole point is to feel out whether the
later ETL stages work against Postgres, so we keep the surface tiny and the SQL
visible.

Connection string defaults to the persistent spike container (port 5433), override
with DATABASE_URL.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg2

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5433/spoor_spike"
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def dsn() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DSN)


def connect():
    """Return a new autocommit-off psycopg2 connection to the spike DB."""
    return psycopg2.connect(dsn())


def init_schema(conn) -> None:
    """Apply schema.sql (idempotent — CREATE TABLE IF NOT EXISTS, never drops)."""
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()
