"""Tests for spike_db.categorise_db against synthetic, fixed-FX corpora.

Pricing is deterministic ZAR and FX is pinned (1 ZAR = 0.05 USD), so ranking and
feasibility are exact without a real rate card.
"""

from __future__ import annotations

from pathlib import Path

import _corpus
import pytest

from spike_db import categorise_db, importer, store
from spoor.categories import CATEGORIES
from spoor.fx import FX

REPO_ROOT = Path(__file__).resolve().parents[2]
FX_FIXED = FX(date="2026-01-01", rates={"USD": 1.0, "ZAR": 0.05})


def _seed(conn, tmp_path, specs):
    eval_dir, raw_dir = _corpus.build_corpus(tmp_path, specs)
    importer.seed_categories(conn)
    importer.import_evaluations(conn, eval_dir, raw_dir)
    conn.commit()


def test_unknown_category_raises(clean_db):
    with pytest.raises(KeyError):
        categorise_db.categorise_one(clean_db, "does-not-exist", FX_FIXED)


def test_ranking_ascending_with_infeasible_last(clean_db, tmp_path):
    conn = clean_db
    _seed(conn, tmp_path, [
        dict(lodge="l", slug="pricey", name="Pricey", adr_per_night=200.0),
        dict(lodge="l", slug="cheap", name="Cheap", adr_per_night=100.0),
        dict(lodge="l", slug="tiny", name="Tiny", adr_per_night=100.0, max_party=2),
    ])
    # corporate-incentive-group is an 8-adult party: Tiny (max 2) never fits.
    rows = categorise_db.categorise_one(conn, "corporate-incentive-group", FX_FIXED)
    assert [r["name"] for r in rows] == ["Cheap", "Pricey", "Tiny"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert rows[0]["included"] is True and rows[0]["low_usd"] == 5  # 100 ZAR * 0.05
    assert rows[-1]["included"] is False
    assert rows[-1]["low_usd"] is None and rows[-1]["feasible_months"] == 0


def test_categorise_rerun_is_idempotent(clean_db, tmp_path):
    conn = clean_db
    _seed(conn, tmp_path, [dict(lodge="l", slug="a", name="A")])
    categorise_db.categorise_one(conn, "honeymoon-couple", FX_FIXED)
    categorise_db.categorise_one(conn, "honeymoon-couple", FX_FIXED)
    assert store.counts(conn)["category_membership"] == 1  # replace, never accumulate


def test_empty_corpus_yields_no_rows(clean_db):
    conn = clean_db
    importer.seed_categories(conn)
    conn.commit()
    assert categorise_db.categorise_one(conn, "honeymoon-couple", FX_FIXED) == []


def test_categorise_all_returns_included_counts(clean_db, tmp_path):
    conn = clean_db
    _seed(conn, tmp_path, [dict(lodge="l", slug="a", name="A")])
    summary = categorise_db.categorise_all(conn, FX_FIXED)
    assert set(summary) == set(CATEGORIES)
    # A single uncapped property fits a 2-adult couple in every month.
    assert summary["honeymoon-couple"] == 1


def test_categorise_main_smoke(clean_db, capsys):
    conn = clean_db
    # Seed the real corpus into the test schema, then drive the CLI (its own connect).
    importer.seed_categories(conn)
    importer.import_evaluations(conn, REPO_ROOT / "data" / "evaluated",
                                REPO_ROOT / "data" / "raw")
    conn.commit()
    rc = categorise_db.main(["--category", "honeymoon-couple"])
    assert rc == 0
    assert "honeymoon-couple" in capsys.readouterr().out


def test_categorise_main_all_categories_smoke(clean_db, capsys):
    conn = clean_db
    importer.seed_categories(conn)
    importer.import_evaluations(conn, REPO_ROOT / "data" / "evaluated",
                                REPO_ROOT / "data" / "raw")
    conn.commit()
    rc = categorise_db.main([])  # no --category -> whole-taxonomy summary branch
    assert rc == 0
    out = capsys.readouterr().out
    assert "categorised" in out and "honeymoon-couple" in out
