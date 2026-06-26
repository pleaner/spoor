"""The fixed traveller taxonomy and the deterministic core of the categorise phase.

The categorise phase inverts the per-property evaluation into a per-category view:
one markdown file per traveller archetype, listing the properties that genuinely
suit it. This module owns the *deterministic* half of that — the fixed taxonomy and
the numbers — while the LLM skill owns membership and the grounded prose.

Each category defines its own **party composition (ages)** rather than borrowing one
of the three precomputed evaluate personas, so the price shown is for a party that
archetype would actually bring. For a given category we drive each evaluated
property's already-generated ``price()`` script across the Benchmark Safari spec
(via ``spoor.benchmark.persona_adr_range``) and report the low–high RACK ADR in USD.
A party that never fits a property excludes it on capacity grounds.

The CLI emits a category's candidate properties + ranges as JSON for the skill to
consume, so the LLM reads computed numbers rather than computing them itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spoor import benchmark

# ── Fixed taxonomy ───────────────────────────────────────────────────────────
# slug → {label, ages}. The ages are the party handed to each property's price().
# Exact adult ages don't matter (pricing scripts treat any age ≥ the adult
# threshold identically), so only party size and children's ages carry signal —
# the several single-/two-adult archetypes share a shape but differ entirely in
# their (LLM-authored, grounded) suitability prose.
ADULT = benchmark.ADULT_AGE  # 40

CATEGORIES: "dict[str, dict]" = {
    "honeymoon-couple": {"label": "Honeymoon couple", "ages": [ADULT, ADULT]},
    "multi-gen-family": {"label": "Multi-gen family",
                         "ages": [ADULT, ADULT, ADULT, ADULT, 10, 14]},
    "wildlife-photographer": {"label": "Wildlife photographer", "ages": [ADULT, ADULT]},
    "citizen-scientist": {"label": "Citizen scientist / conservationist",
                          "ages": [ADULT, ADULT]},
    "ultra-hnw-collector": {"label": "Ultra-HNW collector", "ages": [ADULT, ADULT]},
    "budget-backpacker": {"label": "Budget backpacker", "ages": [ADULT]},
    "solo-adventure-traveller": {"label": "Solo adventure traveller", "ages": [ADULT]},
    "corporate-incentive-group": {"label": "Corporate incentive group",
                                   "ages": [ADULT] * 8},
    "returning-safari-devotee": {"label": "Returning safari devotee",
                                 "ages": [ADULT, ADULT]},
    "eco-conscious-traveller": {"label": "Eco-conscious traveller", "ages": [ADULT, ADULT]},
    "social-media-influencer": {"label": "Social media influencer", "ages": [ADULT]},
    "wellness-retreat-guest": {"label": "Medical / wellness retreat guest",
                               "ages": [ADULT, ADULT]},
    "school-student-group": {"label": "School / student group",
                             "ages": [16, 16, 16, 16, ADULT, ADULT]},
    "birding-specialist": {"label": "Birding specialist", "ages": [ADULT, ADULT]},
}


def discover_properties(evaluated_dir: "str | Path") -> "list[dict]":
    """Find every fully-evaluated property under ``evaluated_dir``.

    A property qualifies when it has both an ``<property>-adr.json`` (the marker of
    a complete evaluation, and the source of its name + benchmark year) and the
    matching ``<property>-pricing.py``. Returns one dict per property with the lodge
    slug, property slug, display name, benchmark year, and the two file paths, sorted
    by lodge then property for stable output.
    """
    root = Path(evaluated_dir)
    found: "list[dict]" = []
    for adr_path in sorted(root.glob("*/*-adr.json")):
        prop_slug = adr_path.name[: -len("-adr.json")]
        pricing_py = adr_path.with_name(f"{prop_slug}-pricing.py")
        eval_md = adr_path.with_name(f"{prop_slug}.md")
        if not pricing_py.is_file():
            continue
        adr = json.loads(adr_path.read_text(encoding="utf-8"))
        found.append({
            "lodge": adr_path.parent.name,
            "property_slug": prop_slug,
            "name": adr.get("property") or prop_slug,
            "year": adr.get("benchmark", {}).get("year"),
            "pricing_py": pricing_py,
            "eval_md": eval_md,
        })
    return found


def category_ranges(category_slug: str, evaluated_dir: "str | Path", fx) -> "list[dict]":
    """Compute every property's USD ADR range for ``category_slug``'s party.

    Drives each discovered property's ``price()`` across the benchmark months for the
    category's party and returns the results sorted by ADR ascending (feasible first,
    cheapest first). Each entry carries the USD low/high range, the feasible-month
    count, and the path to the property's evaluation markdown (for the skill's
    ``[source]`` link). Properties whose party never fits come back with
    ``feasible_months: 0`` and null range, sorted last, so the skill can exclude them
    on capacity grounds.
    """
    if category_slug not in CATEGORIES:
        raise KeyError(
            f"unknown category {category_slug!r}; known: {', '.join(CATEGORIES)}"
        )
    # Imported lazily so the module loads even before the package is on sys.path.
    from spoor.pricing import load_pricing

    ages = CATEGORIES[category_slug]["ages"]
    rows: "list[dict]" = []
    for prop in discover_properties(evaluated_dir):
        price_fn = load_pricing(prop["pricing_py"]).price
        rng = benchmark.persona_adr_range(price_fn, fx, prop["year"], ages)
        rows.append({
            "name": prop["name"],
            "lodge": prop["lodge"],
            "property_slug": prop["property_slug"],
            "eval_md": str(prop["eval_md"]),
            "feasible_months": rng["feasible_months"],
            "low_usd": rng["low_usd"],
            "high_usd": rng["high_usd"],
        })
    # Feasible (low_usd not None) sort ahead of infeasible; within each, by ADR asc.
    rows.sort(key=lambda r: (r["low_usd"] is None, r["low_usd"] or 0, r["name"]))
    return rows


# ── CLI: emit a category's candidate properties + ranges as JSON ─────────────
# Invoked by the categorise skill via Bash so the LLM consumes computed numbers:
#   python -m spoor.categories --category honeymoon-couple --evaluated data/evaluated
def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a traveller category's candidate properties + USD ADR ranges as JSON."
    )
    ap.add_argument("--category", help="Category slug (omit with --list to see all).")
    ap.add_argument("--evaluated", default=str(Path("data/evaluated")),
                    help="Path to the evaluated tree (default: data/evaluated).")
    ap.add_argument("--fx", default=str(Path("config/fx.json")),
                    help="Path to the pinned fx.json.")
    ap.add_argument("--list", action="store_true",
                    help="List the fixed category slugs + labels and exit.")
    args = ap.parse_args(argv)

    if args.list or not args.category:
        print(json.dumps(
            {slug: spec["label"] for slug, spec in CATEGORIES.items()},
            indent=2, ensure_ascii=False))
        return 0

    from spoor.fx import FX

    fx = FX.load(args.fx)
    rows = category_ranges(args.category, args.evaluated, fx)
    print(json.dumps({
        "category": args.category,
        "label": CATEGORIES[args.category]["label"],
        "ages": CATEGORIES[args.category]["ages"],
        "adr_basis": "RACK, USD, low–high across feasible benchmark months",
        "properties": rows,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
