"""Shared paths and helpers for the test suite.

The deterministic-core fixtures (``makanyi``/``tanda``) load the committed pricing
scripts by path and need no third-party libraries — a plain ``pytest`` run stays
stdlib-only. The database fixtures below are guarded behind an optional import of the
``db`` stack, so they simply don't activate when that extra isn't installed; the
``db``-marked tests under ``tests/db/`` ``importorskip`` it themselves.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spoor.pricing import load_pricing

REPO = Path(__file__).resolve().parent.parent
EVALUATED = REPO / "data" / "evaluated"
GOLDEN_RAW = Path(__file__).resolve().parent / "golden" / "raw"


@pytest.fixture(scope="session")
def makanyi():
    """The committed Makanyi pricing module."""
    return load_pricing(EVALUATED / "makanyi-lodge" / "makanyi-private-game-lodge-pricing.py")


@pytest.fixture(scope="session")
def tanda():
    """The committed Tanda Tula Safari Camp pricing module."""
    return load_pricing(EVALUATED / "tanda-tula" / "safari-camp-pricing.py")


# ── database fixtures (active only when the `db` extra is installed) ───────────
# The guide's pattern — a real Postgres, every test rolls back — adapted to an
# environment without the Postgres client binaries: we provision a *disposable
# database* on a reachable server (TEST_DATABASE_URL / DATABASE_URL / the
# docker-compose container) and isolate each test with a SAVEPOINT rollback.

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    from sqlmodel import Session, SQLModel

    _HAS_DB = True
except Exception:  # noqa: BLE001 — the db extra simply isn't installed
    _HAS_DB = False


def _base_url():
    raw = (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg2://postgres:postgres@localhost:5433/spoor"
    )
    return make_url(raw)


def _worker_suffix() -> str:
    return os.getenv("PYTEST_XDIST_WORKER", "main")


def _make_db(admin_engine, name: str) -> None:
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))


def _drop_db(admin_engine, name: str) -> None:
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture(scope="session")
def _admin_engine():
    if not _HAS_DB:
        pytest.skip("db extra not installed")
    engine = create_engine(
        _base_url().set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"no Postgres reachable for db tests: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def _shared_engine(_admin_engine):
    """Schema built once with create_all() (fast); categories seeded once."""
    name = f"spoor_pytest_{_worker_suffix()}"
    _make_db(_admin_engine, name)
    import spoor.models  # noqa: F401 — populate metadata
    from spoor.db import store

    engine = create_engine(_base_url().set(database=name))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        store.seed_categories(session)
        session.commit()
    yield engine
    engine.dispose()
    _drop_db(_admin_engine, name)


@pytest.fixture()
def session(_shared_engine):
    """A session wrapped in an outer transaction that is rolled back after each test."""
    connection = _shared_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        sess.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def fresh_db(_admin_engine):
    """A brand-new empty database (for migration tests); dropped at teardown.

    Yields an unmasked connection string — ``str(URL)`` would hide the password as
    ``***``, which Alembic would then fail to authenticate with.
    """
    name = f"spoor_pytest_fresh_{_worker_suffix()}"
    _make_db(_admin_engine, name)
    yield _base_url().set(database=name).render_as_string(hide_password=False)
    _drop_db(_admin_engine, name)
