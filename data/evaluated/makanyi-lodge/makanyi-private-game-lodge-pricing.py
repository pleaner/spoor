#!/usr/bin/env python3
# rate-card-sha256: 9f94d7c1558b96e5e3b941377fa3b5300f33db12592b7d1e78f690f84673006b
"""Pricing script for Makanyi Private Game Lodge (makanyi-lodge).

Self-contained and stdlib-only. Turns the property's raw rate card into an
explicit pricing function:

    price(start, end, ages=[...]) -> dict

It brute-forces the cheapest valid way to seat a party across the lodge's suites,
applies any objectively-qualifying special, itemises the mandatory conservation
levy, and returns both RACK and STO (trade) figures with the chosen configuration.

Source rate card (transcribed in data/raw/makanyi-lodge/makanyi-private-game-lodge.md
→ "## Rate card"; original PDF: Makanyi-Lodge-2025_2026-Rate-Sheet-TO-25_.pdf,
validity 01 Apr 2025 – 31 Mar 2026, ZAR, per-person-per-night sharing, incl. 15% VAT).

ASSUMPTIONS (surfaced for the completeness assessment):
  * Single flat season: the card quotes one rate for the whole 01 Apr 2025 –
    31 Mar 2026 validity, so every night is priced at that rate. Dates outside the
    validity (incl. any 2026+ benchmark month) reuse it — no newer card published.
  * Conservation levy R620 pppn is the 2025 calendar-year figure (the only one on
    the card); assumed to hold for the benchmark. 2026 levy not confirmed.
  * "No children under 12 unless the lodge is on exclusive use" → a generic party
    with any guest under 12 is treated as INFEASIBLE (exclusive use not assumed).
  * Luxury Suite max occupancy 3 (2 sharing + one 12–18 third person; the card
    defines no third-adult rate). Luxury Pool Suite max 2 (third person "not
    available"). Marula Suite max 4 (2-bedroom, sleeps 4).
  * Honeymoon 50%-off is never auto-applied — it needs proof of marriage (a soft,
    unverifiable qualifier) and is only reported as available-but-not-applied.
  * Per-vehicle Timbavati Gate Levy (R320/vehicle, self-drive only) is EXCLUDED
    under the benchmark's fly-in assumption.
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import json

CURRENCY = "ZAR"
MIN_GUEST_AGE = 12  # no children under 12 (non-exclusive use)

# Mandatory per-person-per-night conservation levy (all ages, payable in advance).
CONSERVATION_LEVY_PPPN = 620.0

# Suites: inventory and max occupancy. Rates handled in room_cost().
SUITES = {
    "Luxury Suite": {"inventory": 5, "max": 3},
    "Luxury Pool Suite": {"inventory": 2, "max": 2},
    "Marula Suite": {"inventory": 1, "max": 4},
}

# Per-person-per-night rates (RACK, STO @ 25% off), single flat season.
_RATES = {
    "Luxury Suite": {"pppn": (21000.0, 15750.0),
                     "single": (31500.0, 23625.0),      # 50% single supplement
                     "third_12_18": (10500.0, 7875.0)},  # 50% of pppn
    "Luxury Pool Suite": {"pppn": (23000.0, 17250.0),
                          "single": (34500.0, 25875.0)},  # 50% single supplement
    "Marula Suite": {"pppn": (23000.0, 17250.0),
                     "single": (46000.0, 34500.0)},       # 100% single surcharge
}


def season_for(d: datetime.date) -> str:
    """One flat season across the card's validity (see ASSUMPTIONS)."""
    return "2025-26"


def room_cost(suite, ages):
    """Per-night (rack, sto, basis) for seating ``ages`` in ``suite``, or None.

    None means the configuration is not allowed by the rate card (e.g. three
    adults in a Luxury Suite, which has no third-adult rate).
    """
    n = len(ages)
    if any(a < MIN_GUEST_AGE for a in ages):
        return None
    r = _RATES[suite]
    if suite == "Luxury Suite":
        if n == 1:
            return (*r["single"], ["single use (50% supplement)"])
        if n == 2:
            return (2 * r["pppn"][0], 2 * r["pppn"][1], ["pppn sharing ×2"])
        if n == 3:
            # Requires exactly one 12–18 third person; no third-adult rate.
            if not any(12 <= a <= 18 for a in ages):
                return None
            return (2 * r["pppn"][0] + r["third_12_18"][0],
                    2 * r["pppn"][1] + r["third_12_18"][1],
                    ["pppn sharing ×2", "third person 12–18 @ 50%"])
        return None
    if suite == "Luxury Pool Suite":
        if n == 1:
            return (*r["single"], ["single use (50% supplement)"])
        if n == 2:
            return (2 * r["pppn"][0], 2 * r["pppn"][1], ["pppn sharing ×2"])
        return None  # third person not available in Pool Suite
    if suite == "Marula Suite":
        if n == 1:
            return (*r["single"], ["single use (100% surcharge)"])
        if 2 <= n <= 4:
            return (n * r["pppn"][0], n * r["pppn"][1], [f"pppn ×{n} (3rd/4th full rate)"])
        return None
    return None


def _best_for_night(ages):
    """Cheapest valid seating of ``ages`` for one night → (rack, sto, rooms)|None.

    Exhaustive search over partitions of the party into rooms and suite-type
    assignments, respecting capacities, age rules, single supplements and
    inventory; minimised on the RACK total (levies are party-fixed, so RACK-cheapest
    is also grand-total-cheapest). Party sizes are tiny (≤8) so this is trivial.
    """
    ages = tuple(sorted(ages, reverse=True))
    inv0 = tuple(sorted({s: SUITES[s]["inventory"] for s in SUITES}.items()))
    memo = {}

    def search(remaining, inv_tuple):
        if not remaining:
            return (0.0, 0.0, [])
        key = (remaining, inv_tuple)
        if key in memo:
            return memo[key]
        inv = dict(inv_tuple)
        first, rest = remaining[0], remaining[1:]
        best = None
        max_extra = max(s["max"] for s in SUITES.values()) - 1
        for k in range(0, min(max_extra, len(rest)) + 1):
            for combo in itertools.combinations(range(len(rest)), k):
                room = (first,) + tuple(rest[i] for i in combo)
                leftover = tuple(rest[i] for i in range(len(rest)) if i not in combo)
                for suite in SUITES:
                    if inv.get(suite, 0) <= 0 or len(room) > SUITES[suite]["max"]:
                        continue
                    rc = room_cost(suite, list(room))
                    if rc is None:
                        continue
                    rack, sto, basis = rc
                    inv2 = dict(inv)
                    inv2[suite] -= 1
                    sub = search(leftover, tuple(sorted(inv2.items())))
                    if sub is None:
                        continue
                    cand = (rack + sub[0], sto + sub[1],
                            [{"suite": suite, "ages": list(room), "basis": basis,
                              "rack": rack, "sto": sto}] + sub[2])
                    if best is None or cand[0] < best[0]:
                        best = cand
        memo[key] = best
        return best

    return search(ages, inv0)


def _infeasible(start, end, ages, reason):
    return {
        "feasible": False, "reason": reason, "currency": CURRENCY,
        "start": start, "end": end, "ages": list(ages),
        "rack_total": 0.0, "sto_total": 0.0, "levy_total": 0.0, "levies": [],
        "rack_grand_total": None, "sto_grand_total": None,
        "rack_adr": None, "sto_adr": None,
        "config": {"rooms": [], "summary": None}, "per_night": [],
        "specials_applied": [], "specials_available_not_applied": [],
        "assumptions": _ASSUMPTIONS, "inclusion": _INCLUSION,
    }


_INCLUSION = ("meets-or-exceeds benchmark — all meals, drinks (incl. house "
             "alcohol), two daily game drives and lodge activities included")
_ASSUMPTIONS = [
    "Single flat season for the whole 2025/26 validity; dates outside it reuse it.",
    "Conservation levy R620 pppn is the 2025 figure, assumed to hold.",
    "No guests under 12 (exclusive use not assumed) → such parties are infeasible.",
    "Honeymoon 50%-off needs proof of marriage (soft) and is never auto-applied.",
    "Per-vehicle gate levy excluded (fly-in assumption).",
]

# ── Specials ─────────────────────────────────────────────────────────────────
# Stay-4-Pay-3 travel windows (exact, from the card). Festive blackout excluded.
_S4P3_WINDOWS = [
    (datetime.date(2025, 11, 1), datetime.date(2025, 12, 19)),
    (datetime.date(2026, 1, 5), datetime.date(2026, 3, 31)),
]


def _in_windows(d, windows):
    return any(lo <= d <= hi for lo, hi in windows)


def _stay4pay3(nights, dates, night_costs):
    """Apply Stay-4-Pay-3 if the whole stay sits in a valid window and ≥4 nights.

    Credits the cheapest night(s) — one free per four. Levy is never discounted.
    """
    if nights < 4 or not all(_in_windows(d, _S4P3_WINDOWS) for d in dates):
        return None
    free = nights // 4
    cheapest = sorted(night_costs, key=lambda c: c[0])[:free]
    return {
        "name": "Stay 4 / Pay 3 (1 free night)",
        "type": "stay-pay",
        "free_nights": free,
        "saving_rack": round(sum(c[0] for c in cheapest), 2),
        "saving_sto": round(sum(c[1] for c in cheapest), 2),
    }


def price(start, end, ages=None):
    """Best (cheapest) price for a party and stay. See module docstring."""
    ages = list(ages or [])
    try:
        s = datetime.date.fromisoformat(start)
        e = datetime.date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError(f"start/end must be ISO dates (YYYY-MM-DD): {exc}")
    nights = (e - s).days
    if nights <= 0:
        return _infeasible(start, end, ages, "end date must be after start date")
    if not ages:
        return _infeasible(start, end, ages, "no guests supplied")
    if any(a < MIN_GUEST_AGE for a in ages):
        return _infeasible(start, end, ages,
                           f"Makanyi does not accept guests under {MIN_GUEST_AGE} "
                           "(non-exclusive use)")

    dates = [s + datetime.timedelta(days=i) for i in range(nights)]
    per_night, night_costs = [], []
    rack_total = sto_total = 0.0
    rooms0 = None
    for d in dates:
        best = _best_for_night(ages)
        if best is None:
            return _infeasible(start, end, ages,
                               f"cannot seat this party in the available suites ({d})")
        rack_total += best[0]
        sto_total += best[1]
        night_costs.append((best[0], best[1]))
        per_night.append({"date": d.isoformat(), "season": season_for(d),
                          "rack": best[0], "sto": best[1]})
        if rooms0 is None:
            rooms0 = best[2]

    # Mandatory levy (all guests are ≥12 here), itemised, never discounted.
    levy_total = CONSERVATION_LEVY_PPPN * len(ages) * nights
    levies = [{"name": "Timbavati Conservation Levy", "band": "per person per night (all ages)",
               "per_person_per_night": CONSERVATION_LEVY_PPPN, "people": len(ages),
               "nights": nights, "total": levy_total}]
    for pn in per_night:
        pn["levy"] = CONSERVATION_LEVY_PPPN * len(ages)

    # Specials. Only objectively-qualifying ones; pick the single best (not combinable).
    applied, available = [], []
    s4p3 = _stay4pay3(nights, dates, night_costs)
    candidates = [c for c in (s4p3,) if c]
    chosen = max(candidates, key=lambda c: c["saving_rack"], default=None)
    for c in candidates:
        if c is chosen:
            applied.append(c)
        else:
            available.append({"name": c["name"], "reason": "not combinable; another special saved more"})
    if s4p3 is None:
        available.append({"name": "Stay 4 / Pay 3 (1 free night)",
                          "reason": "stay is under 4 nights or outside the valid travel windows"})
    # Honeymoon: soft qualifier, never auto-applied.
    if len(ages) == 2 and nights >= 2:
        available.append({"name": "Honeymoon — 50% off one partner",
                          "reason": "requires proof of marriage within 6 months (soft qualifier, not assumed)"})

    save_rack = sum(c["saving_rack"] for c in applied)
    save_sto = sum(c["saving_sto"] for c in applied)
    net_rack = rack_total - save_rack
    net_sto = sto_total - save_sto
    rack_grand = net_rack + levy_total
    sto_grand = net_sto + levy_total

    return {
        "feasible": True, "reason": None, "currency": CURRENCY,
        "start": start, "end": end, "nights": nights, "ages": list(ages),
        "rack_total": round(net_rack, 2), "sto_total": round(net_sto, 2),
        "levy_total": round(levy_total, 2), "levies": levies,
        "rack_grand_total": round(rack_grand, 2), "sto_grand_total": round(sto_grand, 2),
        "rack_adr": round(rack_grand / nights, 2), "sto_adr": round(sto_grand / nights, 2),
        "config": {"rooms": rooms0,
                   "summary": "; ".join(f"{r['suite']} ({len(r['ages'])} guest(s))" for r in rooms0)},
        "per_night": per_night,
        "specials_applied": applied,
        "specials_available_not_applied": available,
        "assumptions": _ASSUMPTIONS, "inclusion": _INCLUSION,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price a stay at Makanyi Private Game Lodge.")
    ap.add_argument("--start", required=True, help="Arrival date YYYY-MM-DD.")
    ap.add_argument("--end", required=True, help="Departure date YYYY-MM-DD.")
    ap.add_argument("--ages", required=True, help="Comma-separated guest ages, e.g. 40,40,15.")
    args = ap.parse_args(argv)
    ages = [int(a) for a in args.ages.split(",") if a.strip()]
    print(json.dumps(price(args.start, args.end, ages), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
