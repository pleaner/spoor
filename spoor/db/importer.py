"""One-time backfill of the existing ``data/evaluated/`` tree into the database.

Walks every fully-evaluated property (one with both ``<property>-adr.json`` and
``<property>-pricing.py``) and loads its property row + evaluation row. Two things the
file-era pipeline left implicit are made first-class here:

* the **lodge-group label**, read from the raw dossier's ``**Lodge group:**`` line
  (``adr.json`` never recorded it); and
* the **grounded prose**, parsed once from the existing ``<property>.md`` ``##`` sections
  into the ``prose`` payload, so imported properties are categorisable off the database.

The prose parse is a deliberate one-time accommodation for the file corpus. The ongoing
evaluate path does *not* parse markdown — it has the model emit structured sections.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from spoor.db import store

# ``## Section`` heading → prose key (exactly two hashes; h3 subsections stay in the body).
_SECTION_KEYS = {
    "value": "value",
    "completeness": "completeness",
    "fit": "fit",
    "self-competitiveness": "self_competitiveness",
    "reputation": "reputation",
}
_H2 = re.compile(r"^##(?!#)\s+(.*\S)\s*$")
_LODGE_GROUP = re.compile(r"\*\*Lodge group:\*\*\s*(.+?)\s*\(([^)]+)\)")


def parse_prose_sections(md: str) -> dict:
    """Split an evaluation markdown into its known ``##`` prose sections (tolerant)."""
    out: dict[str, str] = {}
    current: Optional[str] = None
    buf: list[str] = []
    for line in md.splitlines():
        m = _H2.match(line)
        if m:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = _SECTION_KEYS.get(m.group(1).strip().lower())
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def lodge_label_from_dossier(dossier: Path) -> Optional[str]:
    """Read the lodge-group display label from a raw dossier's ``**Lodge group:**`` line."""
    if not dossier.is_file():
        return None
    m = _LODGE_GROUP.search(dossier.read_text(encoding="utf-8"))
    return m.group(1).strip() if m else None


def import_evaluations(session, evaluated_dir: Path, raw_dir: Path) -> int:
    """Ingest every fully-evaluated property (has both -adr.json and -pricing.py)."""
    evaluated_dir = Path(evaluated_dir)
    raw_dir = Path(raw_dir)
    n = 0
    for adr_path in sorted(evaluated_dir.glob("*/*-adr.json")):
        prop_slug = adr_path.name[: -len("-adr.json")]
        pricing_py = adr_path.with_name(f"{prop_slug}-pricing.py")
        if not pricing_py.is_file():
            continue  # incomplete evaluation — skip, same as discover_properties
        lodge_slug = adr_path.parent.name
        adr = json.loads(adr_path.read_text(encoding="utf-8"))
        dossier = raw_dir / lodge_slug / f"{prop_slug}.md"
        eval_md = adr_path.with_name(f"{prop_slug}.md")
        prose = (
            parse_prose_sections(eval_md.read_text(encoding="utf-8"))
            if eval_md.is_file()
            else {}
        )

        property_id = store.upsert_property(
            session,
            lodge_slug=lodge_slug,
            property_slug=prop_slug,
            name=adr.get("property") or prop_slug,
            lodge_label=lodge_label_from_dossier(dossier),
            currency=adr.get("currency"),
            benchmark_year=adr.get("benchmark", {}).get("year"),
            benchmark_applicable=bool(adr.get("benchmark_applicable", True)),
            inclusion=adr.get("inclusion"),
            pricing_script_path=str(pricing_py.resolve()),
            dossier_path=str(dossier) if dossier.is_file() else None,
        )
        store.put_evaluation(
            session,
            property_id=property_id,
            adr_payload=adr,
            prose=prose,
            fx_date=(adr.get("fx") or {}).get("date"),
        )
        n += 1
    return n
