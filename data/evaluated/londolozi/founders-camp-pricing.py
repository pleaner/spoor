#!/usr/bin/env python3
# rate-card-sha256: acec26d4550a0dd7a816623b602b90a99524efd04b376448c9b34eb6df709282
"""Pricing script for Londolozi Founders Camp (londolozi).

Self-contained and stdlib-only. Turns the property's raw rate card into:

    price(start, end, ages=[...]) -> dict

It brute-forces the cheapest valid way to seat a party across the camp's three
room types (Superior Chalet, Superior Family Chalet, Family Chalet), itemises
the (3-night-capped) Guest Conservation Contribution, and returns both RACK and
STO (trade) figures with the chosen configuration.

This mirrors the CANONICAL Londolozi pricing script (tree-camp-pricing.py);
see that file and the LONDOLOZI GROUP CONVENTIONS below. Founders Camp differs
from Tree Camp chiefly in having multiple room types and accepting children
from age 6 (with a structured child-pricing policy).

Source rate cards (transcribed in data/raw/londolozi/founders-camp.md → "## Rate
card"; original PDFs: londolozi-rack-rates-2026.pdf and -2027.pdf, ZAR, per
person sharing per night, "FOUNDERS CAMP" block).

LONDOLOZI GROUP CONVENTIONS (shared by all five camps):
  * TWO rate cards apply and a stay can straddle them. The 2026 card is valid for
    the booking period 16 Dec 2025 – 15 Dec 2026; the 2027 card 16 Dec 2026 –
    15 Dec 2027. Each NIGHT is priced under the card whose validity covers it
    (boundary: nights dated on/before 15 Dec 2026 → 2026 card, later → 2027 card),
    so a 15-Dec arrival is priced correctly across the boundary.
  * NO trade / STO rate is published anywhere on the Londolozi cards (RACK only),
    so STO == RACK for every figure. Surfaced as an assumption.
  * Single occupancy uses the card's published single rate, which is the per
    person sharing rate + the stated 25% single supplement.
  * The Guest Conservation Contribution is a flat per-person-per-night levy
    "capped at 3 nights" — it is charged for only the first min(nights, 3) nights,
    each at that night's card value, and is never discounted. The card does not
    age-band it or exempt children, so it is applied to all guests (assumption).
  * No minimum-stay requirement appears on the card (min 1 night).
  * Wetu shows no active specials (2026-06-23), so none are applied.
  * Excluded under the benchmark's fly-in assumption: park entrance fees ("to be
    advised", unquantified), the Londolozi/Skukuza road transfer (airstrip
    transfers ARE included), the conditional noise-impact levy, private vehicles
    and pilot rooms.

FOUNDERS CAMP SPECIFICS / ASSUMPTIONS (surfaced for the completeness assessment):
  * Three room types in inventory (rate card "FOUNDERS CAMP" block):
      - Superior Chalet      — 6 units, max 2 (couples). 2 of these 6 are the
        inter-leading pair No.6↔No.7; the other 4 are standalone. Same published
        rate for all six, so they are modelled as one pool of 6 with one
        inter-leading exception (below).
      - Superior Family Chalet — 1 unit, max 4 (2 adults + 2 children 6–18).
      - Family Chalet        — 3 units, max 4 (2 adults + 2 children 6–11).
  * Minimum guest age 6 (Wetu Fast Facts; accommodation from age 6 at Founders).
  * Child pricing (verbatim card policy, encoded faithfully):
      - Children 6–11 sharing pay 50% of the adult per-person-sharing rate
        ("the child rate" on the card).
      - Children 12+ pay the FULL adult rate.
      - Two children 6–11 may share with two adults in a Family Chalet (No.1–3).
      - Two children 6–18 may share with two adults in the Superior Family Chalet.
      - One child 6–11 alone in an inter-leading chalet pays one adult
        per-person-sharing rate (NO single supplement). Modelled as a special
        single-child seating of a Superior Chalet (consumes one Superior unit;
        only one such inter-leading exception exists, so at most one per stay).
  * Age-band modelling note: a 14-year-old is "12+", so pays the adult rate and
    MAY occupy the Superior Family Chalet (6–18 band) but may NOT be one of the
    two "6–11 children" in a Family Chalet. A child 12–18 sharing a Superior
    Family Chalet pays the adult rate (the 50% child rate applies only to 6–11).
  * The standalone Superior Chalets define no child-sharing seating beyond the
    inter-leading exception; children 6–11 are seated in Family / Superior Family
    chalets or (one only) the inter-leading single-child option. The brute-force
    search picks the cheapest valid seating across all of this.
"""

from __future__ import annotations

import argparse
import datetime
import json

CURRENCY = "ZAR"
MIN_GUEST_AGE = 6         # accommodation from age 6 at Founders Camp
CHILD_MAX_AGE = 11        # "children 6–11" pay 50%; 12+ pay the adult rate
SFC_CHILD_MAX_AGE = 18    # Superior Family Chalet child band 6–18
LEVY_CAP_NIGHTS = 3       # Guest Conservation Contribution capped at 3 nights
LEVY_NAME = "Guest Conservation Contribution"

# Per-night rate cards. (pps = adult per person sharing; child = per child sharing,
# = 50% of pps for ages 6–11; single = single occupancy incl. the 25% single
# supplement; levy = Guest Conservation Contribution pppn, "Founders & Varty" band.)
CARD_2026 = {"pps": 39400.0, "child": 19700.0, "single": 49250.0,
             "fam_pps": 34200.0, "fam_child": 17100.0, "fam_single": 42750.0,
             "levy": 573.99}                                            # -2026.pdf
CARD_2027 = {"pps": 44500.0, "child": 22250.0, "single": 55625.0,
             "fam_pps": 38650.0, "fam_child": 19325.0, "fam_single": 48312.50,
             "levy": 610.00}                                           # -2027.pdf
BOUNDARY = datetime.date(2026, 12, 15)  # nights on/before → 2026 card, after → 2027

# Superior Chalet and Superior Family Chalet share the same published rate
# ("pps"/"child"/"single"); Family Chalet uses the "fam_*" rate.
SUITES = {
    "Superior Chalet":        {"inventory": 6, "max": 2},
    "Superior Family Chalet": {"inventory": 1, "max": 4},
    "Family Chalet":          {"inventory": 3, "max": 4},
}


def card_for(d: datetime.date) -> dict:
    return CARD_2026 if d <= BOUNDARY else CARD_2027


def season_for(d: datetime.date) -> str:
    return "2026" if d <= BOUNDARY else "2027"


def room_cost(card, suite, ages):
    """Per-night (rack, sto, basis) for seating ``ages`` in ``suite``, or None.

    STO == RACK (no trade rate published), so both elements are equal. ``ages``
    is the list of guest ages assigned to this one room. Returns None if the
    seating is not a valid configuration for the suite.
    """
    n = len(ages)
    if any(a < MIN_GUEST_AGE for a in ages):
        return None  # no guests under 6
    adults = [a for a in ages if a > CHILD_MAX_AGE]      # 12+ pay adult rate
    kids = [a for a in ages if a <= CHILD_MAX_AGE]       # 6–11 pay child (50%) rate

    if suite == "Superior Chalet":
        # Standalone couple suite, plus the inter-leading single-child exception.
        if n == 1:
            a = ages[0]
            if a <= CHILD_MAX_AGE:
                # One child 6–11 alone in an inter-leading chalet pays one adult
                # per-person-sharing rate, no single supplement.
                return (card["pps"], card["pps"],
                        ["inter-leading single child @ 1× adult pps (no single supp.)"])
            # One adult: single occupancy (25% supplement).
            return (card["single"], card["single"], ["single occupancy (25% supplement)"])
        if n == 2:
            # Couple / 2 sharing — both must be adults (no child-sharing rate
            # defined for the standalone Superior Chalet).
            if kids:
                return None
            return (2 * card["pps"], 2 * card["pps"], ["pps sharing ×2"])
        return None  # max occupancy 2

    if suite == "Superior Family Chalet":
        # 2 adults + up to 2 children 6–18. Children 6–11 pay the 50% child rate;
        # children 12–18 pay the adult rate (they are "12+").
        if not (1 <= n <= 4):
            return None
        if len(adults) > 2:
            return None  # at most two paying-adult-band occupants assumed (2 adults)
        # Children band here is 6–18; a 12–18 guest is already counted in `adults`
        # (full rate) which is correct. 6–11 children billed at the child rate.
        if len(kids) > 2:
            return None
        if n == 1:
            a = ages[0]
            if a <= CHILD_MAX_AGE:
                return None  # a lone child does not occupy a family chalet here
            return (card["single"], card["single"], ["single occupancy (25% supplement)"])
        basis = []
        rack = 0.0
        n_adult = len(adults)
        n_kid = len(kids)
        rack += n_adult * card["pps"]
        if n_adult:
            basis.append(f"adult pps ×{n_adult}")
        rack += n_kid * card["child"]
        if n_kid:
            basis.append(f"child (6–11, 50%) ×{n_kid}")
        return (rack, rack, basis)

    if suite == "Family Chalet":
        # 2 adults + up to 2 children 6–11. Children 12+ may NOT be one of the
        # "6–11 children" here, so any 12+ guest counts as an adult occupant and
        # only two adults fit.
        if not (1 <= n <= 4):
            return None
        if len(adults) > 2:
            return None
        if len(kids) > 2:
            return None
        if n == 1:
            a = ages[0]
            if a <= CHILD_MAX_AGE:
                return None  # a lone child does not occupy a standalone family chalet
            return (card["fam_single"], card["fam_single"],
                    ["single occupancy (25% supplement)"])
        basis = []
        rack = 0.0
        n_adult = len(adults)
        n_kid = len(kids)
        rack += n_adult * card["fam_pps"]
        if n_adult:
            basis.append(f"adult pps ×{n_adult}")
        rack += n_kid * card["fam_child"]
        if n_kid:
            basis.append(f"child (6–11, 50%) ×{n_kid}")
        return (rack, rack, basis)

    return None


def _best_for_night(card, ages):
    """Cheapest valid seating of ``ages`` for one night → (rack, sto, rooms)|None.

    Exhaustive search over partitions of the party into rooms and suite-type
    assignments, respecting capacities, age rules and inventory; minimised on RACK.
    Party sizes are tiny (≤8) so this is trivial.
    """
    import itertools

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
                    rc = room_cost(card, suite, list(room))
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


_INCLUSION = ("meets-or-exceeds benchmark — fully inclusive: all meals, all drinks "
              "(excl. champagne, cellar wines & premium spirits), two daily game "
              "drives, nature walks, airstrip transfers, laundry & WiFi; conservation "
              "levy itemised separately")
_ASSUMPTIONS = [
    "Two rate cards apply; each night priced under its own card (2026 through 15 Dec "
    "2026, 2027 thereafter), so a 15-Dec stay straddles the boundary.",
    "No trade/STO rate published on the Londolozi cards; STO shown equal to RACK.",
    "Guest Conservation Contribution capped at 3 nights and applied to all guests "
    "(the card neither age-bands nor exempts children).",
    "Founders Camp accepts guests from age 6; under-6 parties are infeasible.",
    "Three room types: Superior Chalet (×6, max 2), Superior Family Chalet (×1, max "
    "4), Family Chalet (×3, max 4). The 6 Superior Chalets pool the standalone ×4 and "
    "the inter-leading pair No.6↔7 (same published rate).",
    "Child pricing: 6–11 pay 50% of the adult rate; 12+ pay the full adult rate. Two "
    "6–11 children may share with two adults in a Family Chalet; two 6–18 children in "
    "the Superior Family Chalet (a 12–18 guest pays the adult rate). One 6–11 child "
    "alone in an inter-leading chalet pays one adult pps rate (no single supplement); "
    "only one such inter-leading exception exists.",
    "Standalone Superior Chalets define no child-sharing rate, so children 6–11 are "
    "seated in Family / Superior Family chalets or the single inter-leading option; "
    "the search picks the cheapest valid seating.",
    "Park entrance fees, road transfers, the noise-impact levy and private vehicles "
    "are excluded under the benchmark's fly-in assumption (airstrip transfers included).",
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


def _levy(dates, ages):
    """(levy_total, levies, per_night_levy_list) — capped at 3 nights, all guests,
    each capped night at its own card's value. Never discounted."""
    people = len(ages)
    capped = dates[:LEVY_CAP_NIGHTS]
    # Per-night levy charge for the whole party (0 once past the 3-night cap).
    per_night = [card_for(d)["levy"] * people if i < LEVY_CAP_NIGHTS else 0.0
                 for i, d in enumerate(dates)]
    # Itemise grouped by the distinct pppn value used within the capped window.
    grouped: dict = {}
    for d in capped:
        v = card_for(d)["levy"]
        grouped[v] = grouped.get(v, 0) + 1
    levies = []
    for v in sorted(grouped, reverse=True):
        nights = grouped[v]
        levies.append({"name": LEVY_NAME, "band": "per person per night (all ages)",
                       "per_person_per_night": v, "people": people,
                       "nights": nights, "total": v * people * nights})
    levy_total = sum(l["total"] for l in levies)
    return levy_total, levies, per_night


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
                           f"Founders Camp does not accept guests under {MIN_GUEST_AGE}")

    dates = [s + datetime.timedelta(days=i) for i in range(nights)]
    per_night = []
    rack_total = sto_total = 0.0
    rooms0 = None
    for d in dates:
        best = _best_for_night(card_for(d), ages)
        if best is None:
            return _infeasible(start, end, ages,
                               f"cannot seat this party in the available suites ({d})")
        rack_total += best[0]
        sto_total += best[1]
        per_night.append({"date": d.isoformat(), "season": season_for(d),
                          "rack": best[0], "sto": best[1]})
        if rooms0 is None:
            rooms0 = best[2]

    levy_total, levies, per_night_levy = _levy(dates, ages)
    for pn, lv in zip(per_night, per_night_levy):
        pn["levy"] = lv

    rack_grand = rack_total + levy_total
    sto_grand = sto_total + levy_total

    return {
        "feasible": True, "reason": None, "currency": CURRENCY,
        "start": start, "end": end, "nights": nights, "ages": list(ages),
        "rack_total": round(rack_total, 2), "sto_total": round(sto_total, 2),
        "levy_total": round(levy_total, 2), "levies": levies,
        "rack_grand_total": round(rack_grand, 2), "sto_grand_total": round(sto_grand, 2),
        "rack_adr": round(rack_grand / nights, 2), "sto_adr": round(sto_grand / nights, 2),
        "config": {"rooms": rooms0,
                   "summary": "; ".join(f"{r['suite']} ({len(r['ages'])} guest(s))" for r in rooms0)},
        "per_night": per_night,
        "specials_applied": [],
        "specials_available_not_applied": [],
        "assumptions": _ASSUMPTIONS, "inclusion": _INCLUSION,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price a stay at Londolozi Founders Camp.")
    ap.add_argument("--start", required=True, help="Arrival date YYYY-MM-DD.")
    ap.add_argument("--end", required=True, help="Departure date YYYY-MM-DD.")
    ap.add_argument("--ages", required=True, help="Comma-separated guest ages, e.g. 40,40.")
    args = ap.parse_args(argv)
    ages = [int(a) for a in args.ages.split(",") if a.strip()]
    print(json.dumps(price(args.start, args.end, ages), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
