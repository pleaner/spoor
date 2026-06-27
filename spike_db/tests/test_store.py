"""Unit tests for spike_db.store against the isolated test schema.

Each test seeds its own synthetic rows (no live corpus) and asserts the write
semantics: UPSERT update paths, delete-then-insert membership replacement, the
JOIN-gated corpus read, and both branches of the readable view query.
"""

from __future__ import annotations

from spike_db import store


def _put_property(conn, lodge="l", slug="p", name="P", **over):
    kw = dict(currency="ZAR", benchmark_year=2026, benchmark_applicable=True,
              inclusion=None, pricing_script_path="/x.py", dossier_path=None)
    kw.update(over)
    return store.upsert_property(conn, lodge_slug=lodge, property_slug=slug,
                                 name=name, **kw)


def _member_row(pid, rank=1, low=5, high=9, months=12, included=True):
    return {"property_id": pid, "rank": rank, "low_usd": low, "high_usd": high,
            "feasible_months": months, "included": included}


def test_upsert_property_insert_then_update(clean_db):
    conn = clean_db
    pid = _put_property(conn, name="First", currency="ZAR")
    conn.commit()
    pid2 = _put_property(conn, name="Second", currency="USD",
                         benchmark_applicable=False, inclusion="incl",
                         pricing_script_path="/y.py", dossier_path="/d.md")
    conn.commit()
    assert pid2 == pid  # same identity -> ON CONFLICT update, no new row
    assert store.counts(conn)["properties"] == 1
    with conn.cursor() as cur:
        cur.execute("SELECT name, currency, benchmark_applicable, inclusion, "
                    "dossier_path FROM properties WHERE id = %s", (pid,))
        row = cur.fetchone()
    assert row == ("Second", "USD", False, "incl", "/d.md")


def test_put_evaluation_upsert_updates_blob(clean_db):
    conn = clean_db
    pid = _put_property(conn)
    store.put_evaluation(conn, property_id=pid, adr_json={"v": 1}, fx_date="2026-01-01")
    conn.commit()
    store.put_evaluation(conn, property_id=pid, adr_json={"v": 2}, fx_date="2026-02-02")
    conn.commit()
    assert store.counts(conn)["evaluations"] == 1  # UPSERT on property_id
    with conn.cursor() as cur:
        cur.execute("SELECT adr_json->>'v', fx_date FROM evaluations "
                    "WHERE property_id = %s", (pid,))
        v, fx_date = cur.fetchone()
    assert v == "2"
    assert str(fx_date) == "2026-02-02"


def test_upsert_category_insert_then_update(clean_db):
    conn = clean_db
    store.upsert_category(conn, slug="x", label="X", ages=[40, 40])
    store.upsert_category(conn, slug="x", label="X2", ages=[40])
    conn.commit()
    assert store.counts(conn)["categories"] == 1
    with conn.cursor() as cur:
        cur.execute("SELECT label, ages FROM categories WHERE slug = 'x'")
        label, ages = cur.fetchone()
    assert (label, ages) == ("X2", [40])


def test_replace_category_membership_replaces_and_clears(clean_db):
    conn = clean_db
    store.upsert_category(conn, slug="c", label="C", ages=[40])
    pid = _put_property(conn)
    conn.commit()
    rows = [_member_row(pid)]
    store.replace_category_membership(conn, category_slug="c", rows=rows)
    store.replace_category_membership(conn, category_slug="c", rows=rows)
    conn.commit()
    assert store.counts(conn)["category_membership"] == 1  # replace, not accumulate
    store.replace_category_membership(conn, category_slug="c", rows=[])
    conn.commit()
    assert store.counts(conn)["category_membership"] == 0  # empty rows clears


def test_iter_evaluated_properties_ordered_and_join_gated(clean_db):
    conn = clean_db
    # Two evaluated properties (out of lodge order) + one without an evaluation.
    for lodge, slug in [("zlodge", "b"), ("alodge", "a")]:
        pid = _put_property(conn, lodge=lodge, slug=slug, name=slug)
        store.put_evaluation(conn, property_id=pid, adr_json={}, fx_date=None)
    _put_property(conn, lodge="mlodge", slug="noeval", name="noeval")  # no evaluation
    conn.commit()
    props = store.iter_evaluated_properties(conn)
    # JOIN excludes the un-evaluated property; ordered by (lodge_slug, property_slug).
    assert [p["lodge_slug"] for p in props] == ["alodge", "zlodge"]
    assert "noeval" not in [p["property_slug"] for p in props]


def test_category_listing_no_arg_and_slug_branches(clean_db):
    conn = clean_db
    pid = _put_property(conn)
    for slug in ("c1", "c2"):
        store.upsert_category(conn, slug=slug, label=slug.upper(), ages=[40])
        store.replace_category_membership(conn, category_slug=slug, rows=[_member_row(pid)])
    conn.commit()
    all_rows = store.category_listing(conn)  # no slug -> SELECT * FROM view
    assert {r["category_slug"] for r in all_rows} == {"c1", "c2"}
    one = store.category_listing(conn, "c1")
    assert one and all(r["category_slug"] == "c1" for r in one)


def test_counts_reports_all_tables(clean_db):
    conn = clean_db
    assert store.counts(conn) == {
        "properties": 0, "evaluations": 0,
        "categories": 0, "category_membership": 0,
    }
