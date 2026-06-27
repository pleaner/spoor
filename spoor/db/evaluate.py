"""The evaluate stage's final step: persist one property's evaluation as rows.

Replaces writing ``<property>.md`` + ``<property>-adr.json``. The numbers
(``adr_payload``) are computed by ``spoor.benchmark`` and the prose is authored by the
model as structured sections — this just stores them. The generated
``<property>-pricing.py`` still lives on disk; its path is recorded on the row.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from spoor.db import store
from spoor.db.importer import lodge_label_from_dossier


def persist(
    session,
    *,
    lodge_slug: str,
    property_slug: str,
    adr_payload: dict,
    prose: dict,
    dossier_path: Optional[str] = None,
    pricing_script_path: Optional[str] = None,
) -> int:
    """Upsert the property (incl. lodge label) and write its evaluation row."""
    label = lodge_label_from_dossier(Path(dossier_path)) if dossier_path else None
    property_id = store.upsert_property(
        session,
        lodge_slug=lodge_slug,
        property_slug=property_slug,
        name=adr_payload.get("property") or property_slug,
        lodge_label=label,
        currency=adr_payload.get("currency"),
        benchmark_year=adr_payload.get("benchmark", {}).get("year"),
        benchmark_applicable=bool(adr_payload.get("benchmark_applicable", True)),
        inclusion=adr_payload.get("inclusion"),
        pricing_script_path=pricing_script_path,
        dossier_path=dossier_path,
    )
    store.put_evaluation(
        session,
        property_id=property_id,
        adr_payload=adr_payload,
        prose=prose,
        fx_date=(adr_payload.get("fx") or {}).get("date"),
    )
    return property_id


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Persist one property's evaluation row (numbers + prose) to the database."
    )
    ap.add_argument("--lodge", required=True, help="Lodge slug.")
    ap.add_argument("--property", required=True, help="Property slug.")
    ap.add_argument("--adr", required=True, help="Path to the computed ADR JSON (numbers).")
    ap.add_argument("--prose", required=True,
                    help="Path to the structured prose JSON (keyed by section).")
    ap.add_argument("--dossier", help="Raw dossier path (for the lodge-group label).")
    ap.add_argument("--pricing-script", help="Path to the generated <property>-pricing.py.")
    args = ap.parse_args(argv)

    adr = json.loads(Path(args.adr).read_text(encoding="utf-8"))
    prose = json.loads(Path(args.prose).read_text(encoding="utf-8"))

    from spoor.db.connection import database_url, get_session

    with get_session() as session:
        property_id = persist(
            session,
            lodge_slug=args.lodge,
            property_slug=args.property,
            adr_payload=adr,
            prose=prose,
            dossier_path=args.dossier,
            pricing_script_path=args.pricing_script,
        )
        session.commit()
    print(
        f"→ persisted evaluation for {args.lodge}/{args.property} "
        f"(property_id={property_id}) → {database_url()}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
