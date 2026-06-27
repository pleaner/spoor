"""Backfill the spike DB from the existing file corpus.

Walks data/evaluated/ and ingests each property + its evaluation blob into Postgres,
and seeds the fixed category taxonomy. This is the `spoor db import` of the real plan,
minimal version — enough to give categorise a real corpus to run against off the DB.

Run:  python -m spike_db.importer            (from the repo root)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the sibling `spoor` package importable when run from the repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from spoor.categories import CATEGORIES  # noqa: E402

from . import db, store  # noqa: E402


def import_evaluations(conn, evaluated_dir: Path, raw_dir: Path) -> int:
    """Ingest every fully-evaluated property (has both -adr.json and -pricing.py)."""
    n = 0
    for adr_path in sorted(evaluated_dir.glob("*/*-adr.json")):
        prop_slug = adr_path.name[: -len("-adr.json")]
        pricing_py = adr_path.with_name(f"{prop_slug}-pricing.py")
        if not pricing_py.is_file():
            continue  # incomplete evaluation — skip, same as discover_properties
        lodge_slug = adr_path.parent.name
        adr = json.loads(adr_path.read_text(encoding="utf-8"))
        dossier = raw_dir / lodge_slug / f"{prop_slug}.md"

        property_id = store.upsert_property(
            conn,
            lodge_slug=lodge_slug,
            property_slug=prop_slug,
            name=adr.get("property") or prop_slug,
            currency=adr.get("currency"),
            benchmark_year=adr.get("benchmark", {}).get("year"),
            benchmark_applicable=bool(adr.get("benchmark_applicable", True)),
            inclusion=adr.get("inclusion"),
            pricing_script_path=str(pricing_py.resolve()),
            dossier_path=str(dossier) if dossier.is_file() else None,
        )
        store.put_evaluation(
            conn,
            property_id=property_id,
            adr_json=adr,
            fx_date=(adr.get("fx") or {}).get("date"),
        )
        n += 1
    conn.commit()
    return n


def seed_categories(conn) -> int:
    """Seed the fixed taxonomy from spoor.categories.CATEGORIES."""
    for slug, spec in CATEGORIES.items():
        store.upsert_category(conn, slug=slug, label=spec["label"], ages=spec["ages"])
    conn.commit()
    return len(CATEGORIES)


def main() -> int:
    evaluated = REPO_ROOT / "data" / "evaluated"
    raw = REPO_ROOT / "data" / "raw"
    conn = db.connect()
    try:
        db.init_schema(conn)
        cats = seed_categories(conn)
        props = import_evaluations(conn, evaluated, raw)
        print(f"seeded {cats} categories; imported {props} evaluated properties")
        print("counts:", store.counts(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
