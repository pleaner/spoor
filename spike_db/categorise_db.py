"""Categorise OFF THE DATABASE.

The whole reason `evaluations` is persisted: this reads its corpus from Postgres
(not by globbing data/evaluated), recomputes each property's USD ADR range for a
category's party, and writes the category↔property membership back as rows.

Pricing is recomputed on the fly from the (file-resident, non-persisted) pricing
script — per the design call that pricing runs are cheap and not worth persisting.

This mirrors spoor.categories.category_ranges, but corpus-in and membership-out are
the DB instead of the filesystem, proving categorise can rerun independently off the DB.

Run:  python -m spike_db.categorise_db [--category <slug>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spoor import benchmark  # noqa: E402
from spoor.categories import CATEGORIES  # noqa: E402
from spoor.fx import FX  # noqa: E402
from spoor.pricing import load_pricing  # noqa: E402

from . import db, store  # noqa: E402


def categorise_one(conn, category_slug: str, fx) -> list[dict]:
    """Compute + persist one category's membership from the DB corpus."""
    if category_slug not in CATEGORIES:
        raise KeyError(f"unknown category {category_slug!r}")
    ages = CATEGORIES[category_slug]["ages"]

    rows: list[dict] = []
    for prop in store.iter_evaluated_properties(conn):
        price_fn = load_pricing(prop["pricing_script_path"]).price
        rng = benchmark.persona_adr_range(price_fn, fx, prop["benchmark_year"], ages)
        rows.append({
            "property_id": prop["property_id"],
            "name": prop["name"],
            "low_usd": rng["low_usd"],
            "high_usd": rng["high_usd"],
            "feasible_months": rng["feasible_months"],
        })

    # Feasible (low_usd not None) first, then ADR ascending — same order as the file path.
    rows.sort(key=lambda r: (r["low_usd"] is None, r["low_usd"] or 0, r["name"]))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
        r["included"] = r["feasible_months"] > 0

    store.replace_category_membership(conn, category_slug=category_slug, rows=rows)
    conn.commit()
    return rows


def categorise_all(conn, fx) -> dict[str, int]:
    out: dict[str, int] = {}
    for slug in CATEGORIES:
        rows = categorise_one(conn, slug, fx)
        out[slug] = sum(1 for r in rows if r["included"])
    return out


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Categorise off the spike DB.")
    ap.add_argument("--category", help="One slug; omit to run the whole taxonomy.")
    args = ap.parse_args(argv)

    fx = FX.load(REPO_ROOT / "config" / "fx.json")
    conn = db.connect()
    try:
        db.init_schema(conn)
        if args.category:
            rows = categorise_one(conn, args.category, fx)
            inc = sum(1 for r in rows if r["included"])
            print(f"{args.category}: {inc}/{len(rows)} properties included")
        else:
            summary = categorise_all(conn, fx)
            total = sum(summary.values())
            print(f"categorised {len(summary)} categories; {total} memberships included")
            for slug, n in summary.items():
                print(f"  {slug:32s} {n} included")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
