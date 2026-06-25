"""The Benchmark Safari and the deterministic ADR table.

This module owns the *fixed* benchmark used to make properties comparable, and the
pure function that drives a property's generated ``price()`` across it to produce a
reproducible Average Daily Rate (ADR) table — personas × twelve months, in native
currency and pinned USD. The LLM never hand-assembles this table; this code does.

Benchmark Safari (fixed spec):
  * 5 nights, arriving the 15th of each of the twelve months.
  * Three personas: Couple (2 adults), Family (2 adults + children 6/10/14),
    Group (8 adults). "Adult" is taken as age 40.
  * ADR = (accommodation rate + mandatory per-person-per-night levies) ÷ nights,
    on a RACK basis. STO is carried as a secondary figure.
  * "All meals + one activity per day" is a *minimum* inclusion spec — fully
    inclusive camps are priced on their standard rate as-is.
  * Native currency is canonical; USD is a secondary column from the pinned,
    dated FX rate. Non-safari properties still get a lodging ADR, marked N/A.

The only input is a ``price(start, end, ages)`` callable returning the structured
dict the generated pricing scripts emit; see ``spoor.pricing``.
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import json
import sys
from pathlib import Path

# ── Fixed Benchmark Safari spec ──────────────────────────────────────────────
NIGHTS = 5
ARRIVAL_DAY = 15
ADULT_AGE = 40  # the canonical "adult" age fed to pricing scripts

# Personas: label + the guest ages handed to price(). Family children span the
# typical bands (under-12 / teen / near-adult) so age rules actually exercise.
PERSONAS = {
    "couple": {"label": "Couple (2 adults)", "ages": [ADULT_AGE, ADULT_AGE]},
    "family": {"label": "Family (2 adults + children 6, 10, 14)",
               "ages": [ADULT_AGE, ADULT_AGE, 6, 10, 14]},
    "group": {"label": "Group (8 adults)", "ages": [ADULT_AGE] * 8},
}

BENCHMARK_NA_NOTE = "Benchmark N/A — not a safari product"


def stay_dates(year: int, month: int) -> "tuple[str, str]":
    """Arrival on the 15th, departure NIGHTS later, as ISO date strings."""
    start = datetime.date(year, month, ARRIVAL_DAY)
    end = start + datetime.timedelta(days=NIGHTS)
    return start.isoformat(), end.isoformat()


def _num(value):
    """Coerce a price-result number to float, passing None through."""
    return None if value is None else float(value)


def _cell(price_fn, fx, year: int, month: int, ages: "list[int]") -> dict:
    """Price one persona for one month and shape it into an ADR-table cell.

    ADR is computed *here* from the grand total the script returns, not read from
    the script — the table's arithmetic is this module's responsibility.
    """
    start, end = stay_dates(year, month)
    res = price_fn(start, end, list(ages)) or {}
    currency = res.get("currency")
    feasible = bool(res.get("feasible"))

    cell = {
        "month": month,
        "month_name": calendar.month_name[month],
        "start": start,
        "end": end,
        "nights": NIGHTS,
        "feasible": feasible,
        "reason": res.get("reason"),
        "currency": currency,
    }
    if not feasible:
        # Keep the numeric keys present (as None) so every cell has one shape.
        cell.update(
            rack_adr_native=None, rack_adr_usd=None,
            sto_adr_native=None, sto_adr_usd=None,
            rack_grand_total_native=None, sto_grand_total_native=None,
            levy_total_native=None, config=None,
            specials_applied=[], assumptions=res.get("assumptions", []),
        )
        return cell

    rack_total = _num(res.get("rack_grand_total"))
    sto_total = _num(res.get("sto_grand_total"))
    rack_adr = round(rack_total / NIGHTS, 2) if rack_total is not None else None
    sto_adr = round(sto_total / NIGHTS, 2) if sto_total is not None else None

    cell.update(
        rack_grand_total_native=rack_total,
        sto_grand_total_native=sto_total,
        levy_total_native=_num(res.get("levy_total")),
        rack_adr_native=rack_adr,
        rack_adr_usd=fx.to_usd(rack_adr, currency) if currency else None,
        sto_adr_native=sto_adr,
        sto_adr_usd=fx.to_usd(sto_adr, currency) if currency else None,
        config=(res.get("config") or {}).get("summary"),
        specials_applied=[s.get("name") for s in res.get("specials_applied", [])],
        assumptions=res.get("assumptions", []),
    )
    return cell


def compute_adr_table(
    price_fn,
    fx,
    year: int,
    *,
    is_safari: bool = True,
    inclusion_note: "str | None" = None,
    property_name: "str | None" = None,
) -> dict:
    """Drive ``price_fn`` across the full Benchmark Safari → the ADR table.

    Returns a JSON-serialisable dict: the benchmark spec, an FX provenance block,
    and, per persona, a 12-month list of cells in native currency + pinned USD.
    Non-safari properties are still priced but flagged ``benchmark_applicable:
    false`` with an explanatory note.
    """
    notes: "list[str]" = []
    if not is_safari:
        notes.append(BENCHMARK_NA_NOTE)

    personas_out = {}
    table_currency = None
    for key, spec in PERSONAS.items():
        months = [_cell(price_fn, fx, year, m, spec["ages"]) for m in range(1, 13)]
        feasible_cells = [c for c in months if c["feasible"]]
        if table_currency is None and feasible_cells:
            table_currency = feasible_cells[0]["currency"]
        personas_out[key] = {
            "label": spec["label"],
            "ages": spec["ages"],
            "feasible_months": len(feasible_cells),
            "months": months,
        }

    return {
        "property": property_name,
        "benchmark": {
            "nights": NIGHTS,
            "arrival_day": ARRIVAL_DAY,
            "year": year,
            "adult_age": ADULT_AGE,
            "adr_definition": "(accommodation rate + mandatory pppn levies) / nights, RACK basis",
            "personas": {k: v["ages"] for k, v in PERSONAS.items()},
        },
        "benchmark_applicable": is_safari,
        "notes": notes,
        "inclusion": inclusion_note,
        "currency": table_currency,
        "fx": fx.meta(),
        "personas": personas_out,
    }


# ── CLI: compute one property's ADR JSON deterministically ───────────────────
# Invoked by the evaluate skill via Bash so the LLM never assembles the table:
#   python -m spoor.benchmark --script <pricing.py> --year 2026 --out <adr.json>
def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser(
        description="Compute a property's Benchmark Safari ADR table from its pricing script."
    )
    ap.add_argument("--script", required=True, help="Path to the generated <property>-pricing.py.")
    ap.add_argument("--year", type=int, required=True, help="Benchmark calendar year (per the rate card).")
    ap.add_argument("--fx", default=str(Path("config/fx.json")), help="Path to the pinned fx.json.")
    ap.add_argument("--out", help="Write the ADR JSON here (default: stdout).")
    ap.add_argument("--non-safari", action="store_true",
                    help="Mark Benchmark N/A (still computes a lodging ADR).")
    ap.add_argument("--inclusion", help="Optional inclusion note recorded in the JSON.")
    ap.add_argument("--property-name", help="Optional property name recorded in the JSON.")
    args = ap.parse_args(argv)

    # Imported lazily so the module loads even before the package is on sys.path.
    from spoor.fx import FX
    from spoor.pricing import load_pricing

    price_fn = load_pricing(args.script).price
    fx = FX.load(args.fx)
    table = compute_adr_table(
        price_fn, fx, args.year,
        is_safari=not args.non_safari,
        inclusion_note=args.inclusion,
        property_name=args.property_name,
    )
    text = json.dumps(table, indent=2, ensure_ascii=False)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
