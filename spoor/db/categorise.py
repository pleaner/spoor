"""Categorise off the database.

Two halves with distinct owners, joined here at write time:

* the **numbers** — computed by the deterministic core (``spoor.categories.rank_corpus``,
  the single copy of the pricing loop) over the corpus read from the database; and
* the **judgement** — which properties genuinely suit the archetype, and the grounded
  ``reasoning`` paragraph for each, authored by the model.

``list_candidates`` hands the model the feasible candidates with their numbers and stored
prose to ground its decision; ``persist_category`` takes the model's matches, recomputes
the numbers, and writes the whole category's positive membership in one atomic
delete-then-insert. The model never authors a number; a non-match leaves no row.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spoor import categories
from spoor.db import store


def _db_corpus(session) -> list[dict]:
    """The DB corpus mapped into the shape ``rank_corpus`` expects."""
    return [
        {**p, "pricing_path": p["pricing_script_path"], "year": p["benchmark_year"]}
        for p in store.read_corpus(session)
    ]


def list_candidates(session, category_slug: str, fx) -> list[dict]:
    """Feasible candidates for a category, with numbers + stored prose for grounding.

    Infeasible properties (the party never fits) are dropped — they can never be members.
    """
    ranked = categories.rank_corpus(category_slug, _db_corpus(session), fx)
    out: list[dict] = []
    for r in ranked:
        if r["feasible_months"] == 0:
            continue
        out.append(
            {
                "property_id": r["property_id"],
                "property_slug": r["property_slug"],
                "lodge_slug": r["lodge_slug"],
                "name": r["name"],
                "lodge_label": r["lodge_label"],
                "low_usd": r["low_usd"],
                "high_usd": r["high_usd"],
                "feasible_months": r["feasible_months"],
                "prose": r["prose"],
            }
        )
    return out


def persist_category(session, category_slug: str, judgement: list[dict], fx) -> list[dict]:
    """Write a category's positive membership from the model's judgement, atomically.

    ``judgement`` lists only the matches: ``[{property_slug, reasoning}, …]``. The numbers
    are recomputed here (never taken from the model). A judged property whose party never
    fits is skipped (positives-only). Rerunning replaces the category's rows.
    """
    ranked = categories.rank_corpus(category_slug, _db_corpus(session), fx)
    by_slug = {r["property_slug"]: r for r in ranked}

    matches: list[tuple[dict, str]] = []
    for j in judgement:
        slug = j.get("property_slug")
        reasoning = (j.get("reasoning") or "").strip()
        if not slug:
            raise ValueError("each judgement entry needs a 'property_slug'")
        if not reasoning:
            raise ValueError(f"judgement for {slug!r} has empty 'reasoning' (required)")
        r = by_slug.get(slug)
        if r is None:
            raise KeyError(
                f"{slug!r} is not an evaluated property available for {category_slug!r}"
            )
        if r["low_usd"] is None:
            continue  # positives-only: a party that never fits is not a member
        matches.append((r, reasoning))

    matches.sort(key=lambda m: (m[0]["low_usd"], m[0]["name"]))
    rows = [
        {
            "property_id": r["property_id"],
            "rank": i,
            "adr_low_usd": r["low_usd"],
            "adr_high_usd": r["high_usd"],
            "reasoning": reasoning,
        }
        for i, (r, reasoning) in enumerate(matches, start=1)
    ]
    store.replace_category_membership(session, category_slug=category_slug, rows=rows)
    return rows


def load_judgement(source: str) -> list[dict]:
    """Read a judgement document from a file path or ``-`` (stdin).

    Accepts either a bare list of ``{property_slug, reasoning}`` or the richer
    ``{"category": …, "properties": [...]}`` shape the skill emits.
    """
    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    doc = json.loads(text)
    if isinstance(doc, dict):
        return doc.get("properties", [])
    return doc


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(description="Categorise off the database.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("candidates", help="Emit a category's feasible candidates + numbers + prose.")
    c.add_argument("--category", required=True)
    c.add_argument("--fx", default="config/fx.json")

    p = sub.add_parser("persist", help="Write a category's membership from a judgement document.")
    p.add_argument("--category", required=True)
    p.add_argument("--judgement", default="-", help="Judgement JSON path, or '-' for stdin.")
    p.add_argument("--fx", default="config/fx.json")

    args = ap.parse_args(argv)

    from spoor.db.connection import get_session
    from spoor.fx import FX

    fx = FX.load(args.fx)

    if args.cmd == "candidates":
        with get_session() as session:
            cands = list_candidates(session, args.category, fx)
        print(json.dumps(
            {
                "category": args.category,
                "label": categories.CATEGORIES[args.category]["label"],
                "ages": categories.CATEGORIES[args.category]["ages"],
                "adr_basis": "RACK, USD, low–high across feasible benchmark months",
                "candidates": cands,
            },
            indent=2, ensure_ascii=False,
        ))
        return 0

    judgement = load_judgement(args.judgement)
    with get_session() as session:
        rows = persist_category(session, args.category, judgement, fx)
        session.commit()
    print(f"→ {args.category}: wrote {len(rows)} member(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
