#!/usr/bin/env python3
# rate-card-sha256: 1be00dd49bf999e7f768929879d5727dfd7374826d4b64f4ebf6982964599f4e
"""Pricing script for Tanda Tula Safari Camp (tanda-tula).

Self-contained and stdlib-only. Turns the property's raw rate card into:

    price(start, end, ages=[...]) -> dict

It brute-forces the cheapest valid way to seat a party across the camp's Safari
Suites and Family Suites, applies any objectively-qualifying special, itemises the
age-banded sustainability levy, and returns both RACK and STO25 (trade) figures
with the chosen configuration.

Source rate card (transcribed in data/raw/tanda-tula/safari-camp.md → "## Rate
card"; original PDF: 2026-Tanda-Tula-Rates-STO25.pdf, validity 01 Jan – 31 Dec
2026, ZAR, STO25 = 25% off RACK).

ASSUMPTIONS (surfaced for the completeness assessment):
  * Single flat 2026 season (the card quotes one rate for 01 Jan – 31 Dec 2026);
    every night is priced at that rate.
  * Safari Suite max occupancy 3 (2 paying adults + one 6–16 child; the card
    defines no third-adult rate for a Safari Suite). Family Suite max occupancy 4
    (two bedrooms): base rate covers 1–3 guests, then one additional guest.
  * A lone occupant must be 17+ ("single in own suite: must be 17 or older").
  * The Safari Suite child rate (6–16) requires two paying adults in that suite.
  * "Stay Longer for Less" travel windows are the Wetu-confirmed offers (1 Nov–15
    Dec 2026; 9 Jan–31 Mar 2027; 1 Nov–15 Dec 2027). The website also advertises a
    2026 9 Jan–30 Apr window with no matching Wetu offer — NOT applied (see notes).
  * Honeymoon 50%-off needs proof of wedding date (soft) → never auto-applied.
    The Aerial Safari special is a value-add (a free flight), not a rate discount,
    so it never lowers the price.
  * Per-vehicle Timbavati entrance fee (R360/vehicle, self-drive only) is EXCLUDED
    under the benchmark's fly-in assumption.
"""

from __future__ import annotations

import argparse
import datetime
import itertools
import json

CURRENCY = "ZAR"
MIN_CHILD_AGE = 6      # no guests under 6
ADULT_AGE = 17        # 17+ pays the adult rate
MIN_NIGHTS = 2        # minimum 2-night stay, both suite types

# Age-banded sustainability levy (per person per night), never discounted.
LEVY_ADULT_PPPN = 1815.0  # 12 years and older
LEVY_CHILD_PPPN = 910.0   # 6–11 years

SUITES = {
    "Safari Suite": {"inventory": 7, "max": 3},
    "Family Suite": {"inventory": 2, "max": 4},
}

# RACK / STO25 (25% off) rates, single flat 2026 season.
SS_PPPN = (31500.0, 23625.0)        # per person per night sharing, 17+
SS_SINGLE = (47250.0, 35437.50)     # single adult (50% supplement)
SS_CHILD = (15750.0, 11812.50)      # child 6–16 sharing with 2 paying adults
FS_BASE = (94500.0, 70875.0)        # base rate per night, 1–3 guests
FS_ADD_ADULT = (31500.0, 23625.0)   # additional adult 17+
FS_ADD_CHILD = (15750.0, 11812.50)  # additional child 6–16


def season_for(d: datetime.date) -> str:
    return "2026"


def _is_adult(age):
    return age >= ADULT_AGE


def _is_child(age):
    return MIN_CHILD_AGE <= age < ADULT_AGE


def room_cost(suite, ages):
    """Per-night (rack, sto, basis) for seating ``ages`` in ``suite``, or None."""
    n = len(ages)
    if any(a < MIN_CHILD_AGE for a in ages):
        return None
    if n == 1 and not _is_adult(ages[0]):
        return None  # a lone occupant must be 17+
    adults = [a for a in ages if _is_adult(a)]
    children = [a for a in ages if _is_child(a)]

    if suite == "Safari Suite":
        if n == 1:
            return (*SS_SINGLE, ["single adult (50% supplement)"])
        if n == 2:
            if len(adults) != 2:
                return None  # two sharing must both be adults
            return (2 * SS_PPPN[0], 2 * SS_PPPN[1], ["pppn sharing ×2"])
        if n == 3:
            # exactly 2 paying adults + 1 child 6–16
            if len(adults) != 2 or len(children) != 1:
                return None
            return (2 * SS_PPPN[0] + SS_CHILD[0], 2 * SS_PPPN[1] + SS_CHILD[1],
                    ["pppn sharing ×2", "child 6–16 sharing"])
        return None

    if suite == "Family Suite":
        if 1 <= n <= 3:
            return (*FS_BASE, [f"base rate (1–3 guests), {n} guest(s)"])
        if n == 4:
            # base covers 3; the 4th is the cheapest available category.
            if children:
                add, basis = FS_ADD_CHILD, "additional child 6–16"
            else:
                add, basis = FS_ADD_ADULT, "additional adult 17+"
            return (FS_BASE[0] + add[0], FS_BASE[1] + add[1],
                    ["base rate (3 guests)", basis])
        return None
    return None


def _best_for_night(ages):
    """Cheapest valid seating for one night → (rack, sto, rooms)|None.

    Exhaustive search over party partitions × suite assignments, respecting
    capacities, age rules, single supplements and inventory; minimised on RACK.
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


_INCLUSION = ("meets-or-exceeds benchmark — all meals, drinks (house wines, local "
             "beers & spirits), game drives & guided walks, laundry, airstrip "
             "transfers included")
_ASSUMPTIONS = [
    "Single flat 2026 season; every night priced at the 2026 rate.",
    "Safari Suite max 3 (2 adults + 1 child 6–16); no third-adult rate.",
    "Family Suite max 4: base covers 1–3 guests, then one additional guest.",
    "A lone occupant must be 17+.",
    "Stay-pay windows are the Wetu-confirmed offers; the website's extra 2026 "
    "9 Jan–30 Apr window is not applied.",
    "Honeymoon (proof of wedding) and Aerial Safari (a value-add) never lower the rate.",
    "Per-vehicle entrance fee excluded (fly-in assumption).",
]


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


# ── Specials ─────────────────────────────────────────────────────────────────
_STAYPAY_WINDOWS = [
    (datetime.date(2026, 11, 1), datetime.date(2026, 12, 15)),
    (datetime.date(2027, 1, 9), datetime.date(2027, 3, 31)),
    (datetime.date(2027, 11, 1), datetime.date(2027, 12, 15)),
]


def _in_windows(d, windows):
    return any(lo <= d <= hi for lo, hi in windows)


def _stay_longer_for_less(nights, dates, night_costs):
    """Apply the better of "stay 3 pay 2" / "stay 4 pay 3" if the whole stay
    sits in a valid window. Credits the cheapest night(s); levy never discounted."""
    if nights < 3 or not all(_in_windows(d, _STAYPAY_WINDOWS) for d in dates):
        return None
    free_3p2 = nights // 3
    free_4p3 = nights // 4 if nights >= 4 else 0
    if free_4p3 > free_3p2:
        free, label = free_4p3, "stay 4 pay 3"
    else:
        free, label = free_3p2, "stay 3 pay 2"
    cheapest = sorted(night_costs, key=lambda c: c[0])[:free]
    return {
        "name": f"Stay Longer for Less ({label})",
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
    if nights < MIN_NIGHTS:
        return _infeasible(start, end, ages,
                           f"minimum stay is {MIN_NIGHTS} nights")
    if any(a < MIN_CHILD_AGE for a in ages):
        return _infeasible(start, end, ages,
                           f"Tanda Tula does not accept guests under {MIN_CHILD_AGE}")

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

    # Age-banded levy, itemised, never discounted.
    adults_12plus = [a for a in ages if a >= 12]
    children_6_11 = [a for a in ages if 6 <= a < 12]
    levy_total = (LEVY_ADULT_PPPN * len(adults_12plus)
                  + LEVY_CHILD_PPPN * len(children_6_11)) * nights
    levies = []
    if adults_12plus:
        levies.append({"name": "Sustainability Levy", "band": "12 years and older",
                       "per_person_per_night": LEVY_ADULT_PPPN, "people": len(adults_12plus),
                       "nights": nights, "total": LEVY_ADULT_PPPN * len(adults_12plus) * nights})
    if children_6_11:
        levies.append({"name": "Sustainability Levy", "band": "6–11 years",
                       "per_person_per_night": LEVY_CHILD_PPPN, "people": len(children_6_11),
                       "nights": nights, "total": LEVY_CHILD_PPPN * len(children_6_11) * nights})
    levy_per_night = LEVY_ADULT_PPPN * len(adults_12plus) + LEVY_CHILD_PPPN * len(children_6_11)
    for pn in per_night:
        pn["levy"] = levy_per_night

    # Specials. Only objectively-qualifying; pick the single best (not combinable).
    applied, available = [], []
    slfl = _stay_longer_for_less(nights, dates, night_costs)
    candidates = [c for c in (slfl,) if c]
    chosen = max(candidates, key=lambda c: c["saving_rack"], default=None)
    for c in candidates:
        (applied if c is chosen else available).append(
            c if c is chosen else {"name": c["name"], "reason": "not combinable; another saved more"})
    if slfl is None:
        available.append({"name": "Stay Longer for Less (stay 3 pay 2 / stay 4 pay 3)",
                          "reason": "stay is under 3 nights or outside the valid travel windows"})
    if len(ages) == 2 and nights >= 3:
        available.append({"name": "Honeymoon — 50% off one partner",
                          "reason": "requires proof of wedding date within one year (soft qualifier, not assumed)"})
    available.append({"name": "Aerial Safari — complimentary patrol flight",
                      "reason": "value-add (a free flight), not a rate discount; does not change the price"})

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
    ap = argparse.ArgumentParser(description="Price a stay at Tanda Tula Safari Camp.")
    ap.add_argument("--start", required=True, help="Arrival date YYYY-MM-DD.")
    ap.add_argument("--end", required=True, help="Departure date YYYY-MM-DD.")
    ap.add_argument("--ages", required=True, help="Comma-separated guest ages, e.g. 40,40,10.")
    args = ap.parse_args(argv)
    ages = [int(a) for a in args.ages.split(",") if a.strip()]
    print(json.dumps(price(args.start, args.end, ages), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
