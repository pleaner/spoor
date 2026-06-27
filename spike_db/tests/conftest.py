"""Test fixtures for the spike_db suite — isolated against a throwaway schema.

Every test runs against a dedicated ``spike_test`` schema in the spike Postgres
(port 5433), created on session setup and ``DROP ... CASCADE``'d on teardown, so
the persistent ``public`` corpus is never touched. Isolation is purely via
``search_path``: ``db.init_schema`` and every ``store`` write run against whatever
schema the connection points at, so we steer ``DATABASE_URL``'s libpq ``options``
to ``search_path=spike_test``. That env var also reaches the ``main()`` CLIs, which
open their own ``db.connect()``.

By default the suite SKIPS if Postgres is unreachable (local-dev convenience). Set
``RUN_DB_TESTS=1`` to turn an unreachable DB into a hard ERROR instead — so CI can
never go green having silently run nothing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spike_db import db  # noqa: E402

TEST_SCHEMA = "spike_test"
_TABLES = ("category_membership", "evaluations", "categories", "properties")

# Resolve the base DSN ONCE, before we mutate DATABASE_URL below.
_BASE_DSN = db.dsn()


def _dsn_with_schema(base: str, schema: str) -> str:
    """Append a libpq ``options`` param pinning search_path to ``schema``."""
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}options=-c%20search_path%3D{schema}"


def _admin_connect():
    """A default-search_path connection used to create/drop the test schema."""
    conn = psycopg2.connect(_BASE_DSN)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session")
def schema_conn():
    """Session connection pinned to a freshly-created ``spike_test`` schema."""
    try:
        admin = _admin_connect()
    except Exception as e:  # noqa: BLE001
        if os.getenv("RUN_DB_TESTS"):
            raise RuntimeError(
                f"RUN_DB_TESTS is set but spike Postgres is unreachable on "
                f"{_BASE_DSN}: {e}"
            ) from e
        pytest.skip(f"spike Postgres not reachable on {_BASE_DSN}: {e}")

    with admin.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA {TEST_SCHEMA}")
    admin.close()

    # Point every db.connect() in the suite (incl. the main() CLIs) at the schema.
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _dsn_with_schema(_BASE_DSN, TEST_SCHEMA)

    conn = db.connect()
    db.init_schema(conn)
    try:
        yield conn
    finally:
        conn.close()
        admin = _admin_connect()
        with admin.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {TEST_SCHEMA} CASCADE")
        admin.close()
        if prev is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = prev


@pytest.fixture
def clean_db(schema_conn):
    """Truncate every table before a test so it starts from an empty schema."""
    with schema_conn.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE")
    schema_conn.commit()
    return schema_conn
