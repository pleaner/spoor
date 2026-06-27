"""End-to-end tests for the spoor file→DB spike against the REAL corpus.

These run against the isolated ``spike_test`` schema (see conftest.py), into which
the real ``data/evaluated`` corpus is imported and categorised once per module —
so they exercise the full pipeline on real data without touching the persistent
``public`` corpus. Expected counts are DERIVED from the corpus on disk, never
hardcoded, so a corpus change can't masquerade as a logic regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spike_db import categorise_db, importer, store
from spoor.categories import CATEGORIES
from spoor.fx import FX

REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATED = REPO_ROOT / "data" / "evaluated"
RAW = REPO_ROOT / "data" / "raw"


def _expected_property_count() -> int:
    """Properties the importer will ingest: those with BOTH -adr.json and -pricing.py."""
    n = 0
    for adr in EVALUATED.glob("*/*-adr.json"):
        slug = adr.name[: -len("-adr.json")]
        if adr.with_name(f"{slug}-pricing.py").is_file():
            n += 1
    return n


@pytest.fixture(scope="module")
def populated(schema_conn):
    """Seed + import + fully categorise the real corpus into the test schema once."""
    conn = schema_conn
    with conn.cursor() as cur:
        cur.execute("TRUNCATE category_membership, evaluations, categories, "
                    "properties RESTART IDENTITY CASCADE")
    conn.commit()
    importer.seed_categories(conn)
    importer.import_evaluations(conn, EVALUATED, RAW)
    categorise_db.categorise_all(conn, FX.load(REPO_ROOT / "config" / "fx.json"))
    return conn


def test_import_counts(populated):
    c = store.counts(populated)
    expected = _expected_property_count()
    assert expected > 0  # the corpus actually has evaluated properties
    assert c["properties"] == expected
    assert c["evaluations"] == expected
    assert c["categories"] == len(CATEGORIES)


def test_corpus_read_from_db(populated):
    props = store.iter_evaluated_properties(populated)
    assert len(props) == _expected_property_count()
    for p in props:
        assert Path(p["pricing_script_path"]).is_file()  # path resolves to a real script


def test_evaluation_jsonb_roundtrips(populated):
    with populated.cursor() as cur:
        cur.execute(
            "SELECT adr_json->>'property', adr_json->'benchmark'->>'year' "
            "FROM evaluations e JOIN properties p ON p.id = e.property_id "
            "WHERE p.property_slug = 'makanyi-private-game-lodge'")
        name, year = cur.fetchone()
    assert name == "Makanyi Private Game Lodge"
    assert year == "2026"  # JSONB preserved the nested benchmark dict


def test_honeymoon_membership_ranked_ascending(populated):
    rows = store.category_listing(populated, "honeymoon-couple")
    expected = _expected_property_count()
    assert len(rows) == expected
    assert all(r["included"] for r in rows)  # every property fits a couple
    lows = [float(r["adr_low_usd"]) for r in rows]
    assert lows == sorted(lows)  # ranked cheapest-first
    assert [r["rank"] for r in rows] == list(range(1, expected + 1))


def test_capacity_exclusions_recorded(populated):
    rows = store.category_listing(populated, "multi-gen-family")
    included = [r for r in rows if r["included"]]
    excluded = [r for r in rows if not r["included"]]
    assert included  # a 6-person party fits at least some lodges
    # Whichever properties are excluded must be recorded as capacity-infeasible.
    for r in excluded:
        assert r["feasible_months"] == 0
        assert r["adr_low_usd"] is None


def test_categorise_rerun_is_idempotent(populated):
    fx = FX.load(REPO_ROOT / "config" / "fx.json")
    before = store.counts(populated)["category_membership"]
    categorise_db.categorise_one(populated, "honeymoon-couple", fx)
    categorise_db.categorise_one(populated, "honeymoon-couple", fx)
    assert store.counts(populated)["category_membership"] == before  # replace, not accumulate


def test_readable_view_joins_labels(populated):
    rows = store.category_listing(populated, "birding-specialist")
    assert rows
    r = rows[0]
    assert r["category"] == CATEGORIES["birding-specialist"]["label"]
    assert r["property"] and r["lodge"]  # human-readable names, not ids
