"""Render the deterministic parts of a property's evaluation markdown from its ADR
JSON: the ADR summary table and the completeness checklist spine.

Keeping these in tested Python (not hand-assembled by the LLM) means the 36-cell
table is reproducible and the completeness checklist is a *fixed* list applied the
same way every time. The evaluate skill calls this to produce the scaffold, then
writes the grounded value / completeness / fit / competitiveness prose on top.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Fixed checklist: the fields a usable rate card must have. Each entry is
# (label, list-of-regexes any of which signals "present" in the raw dossier).
COMPLETENESS_CHECKLIST = [
    ("Seasons with exact date ranges", [r"\b\d{1,2}\s+\w+\s+\d{4}\b", r"valid", r"season"]),
    ("Per-room / per-person rates", [r"\bR\s?[\d,]+", r"pppn", r"per person"]),
    ("Currency stated", [r"\bZAR\b", r"\bUSD\b", r"\bRand\b", r"\bR\s?\d"]),
    ("Child / age policy", [r"child", r"age", r"under \d+", r"\d+\s*[-–]\s*\d+\s*year"]),
    ("Single supplement", [r"single supplement", r"single use", r"single occupancy", r"supplement"]),
    ("Mandatory levies", [r"levy", r"conservation", r"sustainability", r"community"]),
    ("Minimum stay", [r"minimum.{0,12}night", r"min.{0,6}stay", r"\bnight stay"]),
    ("Check-in / check-out", [r"check[\s-]?in", r"check[\s-]?out"]),
    ("Cancellation terms", [r"cancel", r"no[\s-]?show", r"penalty"]),
    ("Validity period", [r"valid", r"validity", r"01 \w+ \d{4}\s*[–-]"]),
    ("Inclusions / exclusions", [r"includ", r"exclud", r"not included"]),
]


def _fmt(n):
    """Thousands-separated number, or '—' for None."""
    return "—" if n is None else f"{n:,.0f}"


def render_adr_table(adr: dict) -> str:
    """A per-persona ADR table (rows = months) plus a summary, as markdown."""
    cur = adr.get("currency") or "native"
    lines = []

    # Summary: one row per persona with feasible-month count and RACK ADR range.
    lines.append("### ADR summary (RACK basis)\n")
    lines.append(f"| Persona | Feasible months | Low ADR ({cur}) | High ADR ({cur}) | Low ADR (USD) | High ADR (USD) |")
    lines.append("|---|---|---|---|---|---|")
    for key, p in adr["personas"].items():
        adrs = [(c["rack_adr_native"], c["rack_adr_usd"]) for c in p["months"] if c["feasible"]]
        if adrs:
            lo_n = min(a[0] for a in adrs); hi_n = max(a[0] for a in adrs)
            lo_u = min(a[1] for a in adrs); hi_u = max(a[1] for a in adrs)
            lines.append(f"| {p['label']} | {p['feasible_months']}/12 | {_fmt(lo_n)} | "
                         f"{_fmt(hi_n)} | {_fmt(lo_u)} | {_fmt(hi_u)} |")
        else:
            lines.append(f"| {p['label']} | 0/12 | — | — | — | — |")
    lines.append("")

    # Detail: one table per persona, month by month.
    for key, p in adr["personas"].items():
        lines.append(f"### {p['label']} — monthly ADR\n")
        lines.append(f"| Month | RACK ADR ({cur}) | RACK ADR (USD) | STO ADR ({cur}) | Config / notes |")
        lines.append("|---|---|---|---|---|")
        for c in p["months"]:
            if not c["feasible"]:
                lines.append(f"| {c['month_name']} | — | — | — | _infeasible: {c.get('reason','')}_ |")
                continue
            note = c.get("config") or ""
            if c.get("specials_applied"):
                note += f" · special: {', '.join(c['specials_applied'])}"
            lines.append(f"| {c['month_name']} | {_fmt(c['rack_adr_native'])} | "
                         f"{_fmt(c['rack_adr_usd'])} | {_fmt(c['sto_adr_native'])} | {note} |")
        lines.append("")

    fx = adr.get("fx", {})
    lines.append(f"_ADR = (accommodation + mandatory pppn levies) ÷ {adr['benchmark']['nights']} nights, "
                 f"RACK basis. USD via pinned FX rate {fx.get('rates', {}).get(cur, '?')} "
                 f"{cur}→USD dated {fx.get('date','?')}._")
    return "\n".join(lines)


def detect_completeness(dossier_md: str) -> "list[tuple[str, bool]]":
    """Best-effort present/absent for each fixed checklist field, by scanning the
    raw dossier's rate-card section. The evaluate skill should verify these."""
    from spoor.freshness import rate_card_section
    section = rate_card_section(dossier_md).lower() or dossier_md.lower()
    out = []
    for label, patterns in COMPLETENESS_CHECKLIST:
        present = any(re.search(p, section, re.I) for p in patterns)
        out.append((label, present))
    return out


def render_completeness(adr: dict, dossier_md: "str | None" = None) -> str:
    """The completeness spine: fixed checklist + the script-generation assumptions."""
    lines = ["### Completeness checklist\n", "| Field | Present? |", "|---|---|"]
    if dossier_md is not None:
        for label, present in detect_completeness(dossier_md):
            lines.append(f"| {label} | {'✓' if present else '✗'} |")
    else:
        for label, _ in COMPLETENESS_CHECKLIST:
            lines.append(f"| {label} | ? |")
    lines.append("")

    # Surface the pricing-script assumptions as concrete findings.
    assumptions = []
    for p in adr["personas"].values():
        for c in p["months"]:
            for a in c.get("assumptions", []):
                if a not in assumptions:
                    assumptions.append(a)
    if assumptions:
        lines.append("**Assumptions the pricing script had to make (each a real gap):**\n")
        for a in assumptions:
            lines.append(f"- {a}")
        lines.append("")
    return "\n".join(lines)


def render_scaffold(adr: dict, dossier_md: "str | None" = None) -> str:
    """Full evaluation-markdown scaffold: header, table, completeness spine, and
    prose placeholders for the evaluate skill to fill (grounded in the numbers)."""
    name = adr.get("property") or "Property"
    na = "" if adr.get("benchmark_applicable", True) else f"\n> **{adr['notes'][0]}**\n"
    return f"""# {name} — Evaluation
{na}
{render_adr_table(adr)}

## Value
_(grounded prose: what a guest gets at each price tier — cite the ADR numbers above.)_

## Completeness

{render_completeness(adr, dossier_md)}
_(grounded prose: discuss the gaps above, citing the raw dossier.)_

## Fit
_(grounded prose: which traveller/group this camp suits — from its rooms, capacities,
child policy and positioning.)_

## Self-competitiveness
_(grounded prose: rack-vs-trade spread, seasonal spread, single-supplement burden —
all computable from the ADR JSON. No cross-property comparison here.)_
"""


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Render evaluation markdown scaffold from an ADR JSON.")
    ap.add_argument("--adr", required=True, help="Path to <property>-adr.json.")
    ap.add_argument("--dossier", help="Path to the raw dossier (for the completeness checklist).")
    ap.add_argument("--out", help="Write here (default: stdout).")
    args = ap.parse_args(argv)
    adr = json.loads(Path(args.adr).read_text(encoding="utf-8"))
    dossier = Path(args.dossier).read_text(encoding="utf-8") if args.dossier else None
    md = render_scaffold(adr, dossier)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
