"""Tests for spike_db.importer against synthetic tmp_path corpora.

Counts are derived from what each test writes (never the live 7), and the skip,
empty-corpus, NULL-field, and CLI paths are all exercised.
"""

from __future__ import annotations

import _corpus

from spike_db import importer, store
from spoor.categories import CATEGORIES


def test_import_counts_match_corpus(clean_db, tmp_path):
    conn = clean_db
    eval_dir, raw_dir = _corpus.build_corpus(tmp_path, [
        dict(lodge="l1", slug="a", name="A"),
        dict(lodge="l1", slug="b", name="B"),
        dict(lodge="l2", slug="c", name="C"),
    ])
    n = importer.import_evaluations(conn, eval_dir, raw_dir)
    assert n == 3
    assert store.counts(conn)["properties"] == 3
    assert store.counts(conn)["evaluations"] == 3


def test_incomplete_evaluation_skipped(clean_db, tmp_path):
    conn = clean_db
    eval_dir, raw_dir = _corpus.build_corpus(tmp_path, [
        dict(lodge="l", slug="full", name="Full"),
        dict(lodge="l", slug="partial", name="Partial", with_pricing=False),
    ])
    n = importer.import_evaluations(conn, eval_dir, raw_dir)
    assert n == 1  # property missing -pricing.py is skipped
    assert [p["property_slug"] for p in store.iter_evaluated_properties(conn)] == ["full"]


def test_import_is_idempotent(clean_db, tmp_path):
    conn = clean_db
    eval_dir, raw_dir = _corpus.build_corpus(tmp_path, [dict(lodge="l", slug="a", name="A")])
    importer.import_evaluations(conn, eval_dir, raw_dir)
    importer.import_evaluations(conn, eval_dir, raw_dir)
    assert store.counts(conn)["properties"] == 1  # UPSERT, no duplicates


def test_empty_corpus_imports_nothing(clean_db, tmp_path):
    conn = clean_db
    eval_dir = tmp_path / "evaluated"
    raw_dir = tmp_path / "raw"
    eval_dir.mkdir()
    raw_dir.mkdir()
    assert importer.import_evaluations(conn, eval_dir, raw_dir) == 0
    assert store.counts(conn)["properties"] == 0


def test_none_fields_persist_as_null(clean_db, tmp_path):
    conn = clean_db
    eval_dir, raw_dir = _corpus.build_corpus(tmp_path, [
        dict(lodge="l", slug="a", name="A", currency=None, inclusion=None,
             benchmark_year=None, fx_date=None, with_dossier=False),
    ])
    importer.import_evaluations(conn, eval_dir, raw_dir)
    with conn.cursor() as cur:
        cur.execute("SELECT p.currency, p.benchmark_year, p.inclusion, p.dossier_path, "
                    "e.fx_date FROM properties p JOIN evaluations e ON e.property_id = p.id")
        row = cur.fetchone()
    assert row == (None, None, None, None, None)


def test_seed_categories_seeds_full_taxonomy(clean_db):
    conn = clean_db
    n = importer.seed_categories(conn)
    assert n == len(CATEGORIES)
    assert store.counts(conn)["categories"] == len(CATEGORIES)


def test_importer_main_smoke(clean_db, capsys):
    # main() opens its own db.connect() (-> spike_test via DATABASE_URL) and reads
    # the real corpus; we assert it runs clean and reports, not exact counts.
    rc = importer.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "imported" in out
    assert store.counts(clean_db)["properties"] > 0  # main() committed into the schema
