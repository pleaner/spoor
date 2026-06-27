"""Phase 1 database tests: schema/migrations and the property+evaluation round-trip.

Marked ``db`` and run against a disposable database (see ``conftest.py``). A plain
``pytest`` run never reaches these — the directory is skipped without the ``db`` extra.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

pytest.importorskip("sqlmodel")
pytest.importorskip("psycopg2")

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

import spoor.models  # noqa: E402
from spoor.db import store  # noqa: E402
from spoor.db.migrate import upgrade_to_head  # noqa: E402

EXPECTED_TABLES = {"properties", "evaluations", "categories", "category_membership"}


def _tables(engine) -> set:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


# ── migrations ────────────────────────────────────────────────────────────────

def test_migration_creates_tables_and_view(fresh_db):
    upgrade_to_head(str(fresh_db))
    engine = create_engine(fresh_db)
    try:
        assert EXPECTED_TABLES <= _tables(engine)
        assert "category_listing" in inspect(engine).get_view_names()
    finally:
        engine.dispose()


def test_migration_is_idempotent(fresh_db):
    upgrade_to_head(str(fresh_db))
    upgrade_to_head(str(fresh_db))  # second run is a no-op
    engine = create_engine(fresh_db)
    try:
        with engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()
        assert n == 1  # exactly one row, parked at head
        assert EXPECTED_TABLES <= _tables(engine)
    finally:
        engine.dispose()


def test_alembic_schema_matches_models(fresh_db):
    # A fresh database migrated by Alembic carries exactly the model-defined tables.
    upgrade_to_head(str(fresh_db))
    engine = create_engine(fresh_db)
    try:
        assert set(SQLModel.metadata.tables.keys()) == _tables(engine)
    finally:
        engine.dispose()


# ── property + evaluation round-trip ─────────────────────────────────────────

def test_property_and_evaluation_roundtrip(session):
    pid = store.upsert_property(
        session,
        lodge_slug="x-lodge",
        property_slug="camp-x",
        name="Camp X",
        lodge_label="X Lodge",
        currency="ZAR",
        benchmark_year=2026,
        pricing_script_path="/tmp/camp-x-pricing.py",
    )
    store.put_evaluation(
        session,
        property_id=pid,
        adr_payload={"property": "Camp X", "benchmark": {"year": 2026}, "currency": "ZAR"},
        prose={"value": "strong", "fit": "couples"},
        fx_date="2026-06-24",
    )

    corpus = store.read_corpus(session)
    assert len(corpus) == 1
    row = corpus[0]
    assert row["name"] == "Camp X"
    assert row["lodge_label"] == "X Lodge"
    assert row["benchmark_year"] == 2026
    assert row["adr_payload"]["benchmark"]["year"] == 2026  # JSONB round-trips
    assert row["prose"]["fit"] == "couples"


def test_upsert_property_is_idempotent(session):
    first = store.upsert_property(session, lodge_slug="x", property_slug="c", name="First")
    second = store.upsert_property(session, lodge_slug="x", property_slug="c", name="Second")
    assert first == second  # same identity → same row, updated in place
    obj = session.get(spoor.models.Property, first)
    assert obj.name == "Second"


def test_categories_seeded(session):
    from spoor.categories import CATEGORIES

    n = session.execute(text("SELECT count(*) FROM categories")).scalar_one()
    assert n == len(CATEGORIES) == 14
