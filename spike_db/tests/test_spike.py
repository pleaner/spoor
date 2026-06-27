"""Unit tests for the spoor file→DB spike.

Run against the PERSISTENT spike container (port 5433). The tests never drop tables
— every op is idempotent (UPSERT / replace), so after the run the DB is fully
populated for inspection, exactly as the design asks.

    cd <worktree> && .venv/bin/python -m pytest spike_db/tests -v

Skips cleanly if the container isn't reachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spoor.categories import CATEGORIES  # noqa: E402
from spoor.fx import FX  # noqa: E402

from spike_db import categorise_db, db, importer, store  # noqa: E402


@pytest.fixture(scope="module")
def conn():
    try:
        c = db.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"spike Postgres not reachable on {db.dsn()}: {e}")
    # Idempotent bring-up: schema + seed + import + full categorise.
    db.init_schema(c)
    importer.seed_categories(c)
    importer.import_evaluations(c, REPO_ROOT / "data" / "evaluated", REPO_ROOT / "data" / "raw")
    fx = FX.load(REPO_ROOT / "config" / "fx.json")
    categorise_db.categorise_all(c, fx)
    yield c
    c.close()


def test_schema_is_idempotent(conn):
    db.init_schema(conn)  # second apply must not raise
    db.init_schema(conn)


def test_import_counts(conn):
    c = store.counts(conn)
    assert c["properties"] == 7
    assert c["evaluations"] == 7
    assert c["categories"] == len(CATEGORIES) == 14


def test_property_upsert_is_idempotent(conn):
    before = store.counts(conn)["properties"]
    importer.import_evaluations(conn, REPO_ROOT / "data" / "evaluated", REPO_ROOT / "data" / "raw")
    assert store.counts(conn)["properties"] == before  # UPSERT, no duplicates


def test_evaluation_jsonb_roundtrips(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT adr_json->>'property', adr_json->'benchmark'->>'year' "
            "FROM evaluations e JOIN properties p ON p.id=e.property_id "
            "WHERE p.property_slug = 'makanyi-private-game-lodge'")
        name, year = cur.fetchone()
    assert name == "Makanyi Private Game Lodge"
    assert year == "2026"  # JSONB preserved the nested benchmark dict


def test_corpus_read_from_db(conn):
    props = store.iter_evaluated_properties(conn)
    assert len(props) == 7
    for p in props:
        assert Path(p["pricing_script_path"]).is_file()  # path still resolves to a real script


def test_honeymoon_membership_ranked_ascending(conn):
    rows = store.category_listing(conn, "honeymoon-couple")
    assert len(rows) == 7
    assert all(r["included"] for r in rows)  # every property fits a couple
    lows = [float(r["adr_low_usd"]) for r in rows]
    assert lows == sorted(lows)  # ranked cheapest-first
    assert [r["rank"] for r in rows] == list(range(1, 8))


def test_capacity_exclusions_recorded(conn):
    rows = store.category_listing(conn, "multi-gen-family")
    included = [r for r in rows if r["included"]]
    excluded = [r for r in rows if not r["included"]]
    assert included and excluded  # a 6-person party fits some lodges, not others
    for r in excluded:
        assert r["feasible_months"] == 0
        assert r["adr_low_usd"] is None


def test_categorise_rerun_is_idempotent(conn):
    fx = FX.load(REPO_ROOT / "config" / "fx.json")
    before = store.counts(conn)["category_membership"]
    categorise_db.categorise_one(conn, "honeymoon-couple", fx)
    categorise_db.categorise_one(conn, "honeymoon-couple", fx)
    assert store.counts(conn)["category_membership"] == before  # replace, never accumulate


def test_readable_view_joins_labels(conn):
    rows = store.category_listing(conn, "birding-specialist")
    assert rows
    r = rows[0]
    assert r["category"] == CATEGORIES["birding-specialist"]["label"]
    assert r["property"] and r["lodge"]  # human-readable names, not ids
